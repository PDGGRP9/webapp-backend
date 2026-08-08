from __future__ import annotations

import json

from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.db import IntegrityError, connection, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods


TOKEN_SALT = "pdg.braceletconnecte.auth"
TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 7


def _json_response(payload: dict[str, object], status: int = 200) -> JsonResponse:
    return JsonResponse(payload, status=status)


def _parse_json(request) -> dict[str, object]:  # noqa: ANN001
    if not request.body:
        return {}
    try:
        decoded = request.body.decode("utf-8")
        return json.loads(decoded) if decoded else {}
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON body") from exc


def _required(data: dict[str, object], fields: list[str]) -> list[str]:
    missing = []
    for field in fields:
        value = data.get(field)
        if value is None or value == "":
            missing.append(field)
    return missing


def _row_to_user(row: tuple[object, ...]) -> dict[str, object]:
    return {
        "id": row[0],
        "email": row[1],
        "username": row[2],
        "first_name": row[4],
        "last_name": row[5],
        "is_active": bool(row[6]),
        "is_staff": bool(row[7]),
        "is_superuser": bool(row[8]),
        "created_at": row[9],
        "updated_at": row[10],
    }


def _row_to_bracelet(row: tuple[object, ...]) -> dict[str, object]:
    return {
        "id": row[0],
        "user_id": row[1],
        "device_uid": row[2],
        "serial_number": row[3],
        "display_name": row[4],
        "firmware_version": row[5],
        "mac_address": row[6],
        "status": row[7],
        "paired_at": row[8],
        "last_seen_at": row[9],
        "created_at": row[10],
        "updated_at": row[11],
    }


def _issue_token(user: dict[str, object]) -> str:
    payload = {
        "user_id": user["id"],
        "email": user["email"],
        "username": user["username"],
        "iat": timezone.now().isoformat(),
    }
    return signing.dumps(payload, salt=TOKEN_SALT)


def _decode_token_from_request(request):  # noqa: ANN001
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None
    try:
        return signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE_SECONDS)
    except signing.BadSignature:
        return None
    except signing.SignatureExpired:
        return None


def _ensure_user_exists(user_id: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM users WHERE id = %s",
            [user_id],
        )
        return cursor.fetchone() is not None


def _get_user_by_email(email: str):  # noqa: ANN001
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, email, username, password_hash, first_name, last_name,
                   is_active, is_staff, is_superuser, created_at, updated_at
            FROM users
            WHERE email = %s
            """,
            [email],
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "email": row[1],
            "username": row[2],
            "password_hash": row[3],
            "first_name": row[4],
            "last_name": row[5],
            "is_active": bool(row[6]),
            "is_staff": bool(row[7]),
            "is_superuser": bool(row[8]),
            "created_at": row[9],
            "updated_at": row[10],
        }


def _get_bracelet_by_identifier(device_uid: str | None, serial_number: str | None):
    clauses = []
    params: list[object] = []
    if device_uid:
        clauses.append("device_uid = %s")
        params.append(device_uid)
    if serial_number:
        clauses.append("serial_number = %s")
        params.append(serial_number)
    if not clauses:
        return None

    query = f"""
        SELECT id, user_id, device_uid, serial_number, display_name, firmware_version,
               mac_address, status, paired_at, last_seen_at, created_at, updated_at
        FROM bracelets
        WHERE {' OR '.join(clauses)}
        ORDER BY id ASC
        LIMIT 1
    """
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()
        return _row_to_bracelet(row) if row is not None else None


def _upsert_bracelet(payload: dict[str, object]) -> dict[str, object]:
    now = timezone.now().isoformat()
    device_uid = payload.get("device_uid")
    serial_number = payload.get("serial_number")
    display_name = payload.get("display_name", "Bracelet de test")
    firmware_version = payload.get("firmware_version")
    mac_address = payload.get("mac_address")

    existing = _get_bracelet_by_identifier(device_uid, serial_number)
    with connection.cursor() as cursor:
        if existing is None:
            cursor.execute(
                """
                INSERT INTO bracelets (
                    user_id, device_uid, serial_number, display_name,
                    firmware_version, mac_address, status, paired_at,
                    last_seen_at, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, user_id, device_uid, serial_number, display_name, firmware_version,
                          mac_address, status, paired_at, last_seen_at, created_at, updated_at
                """,
                [
                    None,
                    device_uid,
                    serial_number,
                    display_name,
                    firmware_version,
                    mac_address,
                    "active",
                    None,
                    now,
                    now,
                    now,
                ],
            )
        else:
            cursor.execute(
                """
                UPDATE bracelets
                SET serial_number = %s,
                    display_name = %s,
                    firmware_version = %s,
                    mac_address = %s,
                    last_seen_at = %s,
                    updated_at = %s
                WHERE id = %s
                RETURNING id, user_id, device_uid, serial_number, display_name, firmware_version,
                          mac_address, status, paired_at, last_seen_at, created_at, updated_at
                """,
                [
                    serial_number,
                    display_name,
                    firmware_version,
                    mac_address,
                    now,
                    now,
                    existing["id"],
                ],
            )

        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Unable to persist bracelet")
        return _row_to_bracelet(row)


def _insert_measurement(bracelet_id: int, payload: dict[str, object]) -> dict[str, object]:
    now = timezone.now().isoformat()
    captured_at = payload.get("captured_at") or now
    raw_payload = json.dumps(payload)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO biometrics_measurements (
                bracelet_id, captured_at, heart_rate_bpm, spo2_percent, step_count,
                motion_level, signal_quality, raw_payload, source_topic, received_at, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, bracelet_id, captured_at, heart_rate_bpm, spo2_percent, step_count,
                      motion_level, signal_quality, raw_payload, source_topic, received_at, created_at
            """,
            [
                bracelet_id,
                captured_at,
                payload.get("heart_rate_bpm"),
                payload.get("spo2_percent"),
                payload.get("step_count", 0),
                payload.get("motion_level"),
                payload.get("signal_quality"),
                raw_payload,
                payload.get("source_topic"),
                now,
                now,
            ],
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Unable to persist measurement")
        return {
            "id": row[0],
            "bracelet_id": row[1],
            "captured_at": row[2],
            "heart_rate_bpm": row[3],
            "spo2_percent": row[4],
            "step_count": row[5],
            "motion_level": row[6],
            "signal_quality": row[7],
            "raw_payload": row[8],
            "source_topic": row[9],
            "received_at": row[10],
            "created_at": row[11],
        }


@require_http_methods(["GET"])
def health(request):  # noqa: ANN001
    return _json_response({"status": "ok", "service": "webapp-backend"})


@require_http_methods(["POST"])
def register(request):  # noqa: ANN001
    try:
        payload = _parse_json(request)
    except ValueError as exc:
        return _json_response({"detail": str(exc)}, status=400)

    missing = _required(payload, ["email", "username", "password"])
    if missing:
        return _json_response({"detail": "Missing required fields", "missing": missing}, status=400)

    now = timezone.now().isoformat()
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                        email, username, password_hash, first_name, last_name,
                        is_active, is_staff, is_superuser, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, email, username, password_hash, first_name, last_name,
                              is_active, is_staff, is_superuser, created_at, updated_at
                    """,
                    [
                        payload["email"],
                        payload["username"],
                        make_password(str(payload["password"])),
                        payload.get("first_name", ""),
                        payload.get("last_name", ""),
                        True,
                        False,
                        False,
                        now,
                        now,
                    ],
                )
                row = cursor.fetchone()
    except IntegrityError:
        return _json_response({"detail": "Email or username already exists"}, status=409)

    if row is None:
        return _json_response({"detail": "Unable to create user"}, status=500)

    user = _row_to_user(row)
    user["token"] = _issue_token(user)
    return _json_response({"user": user}, status=201)


@require_http_methods(["POST"])
def login(request):  # noqa: ANN001
    try:
        payload = _parse_json(request)
    except ValueError as exc:
        return _json_response({"detail": str(exc)}, status=400)

    missing = _required(payload, ["email", "password"])
    if missing:
        return _json_response({"detail": "Missing required fields", "missing": missing}, status=400)

    user = _get_user_by_email(str(payload["email"]))
    if user is None or not user["is_active"]:
        return _json_response({"detail": "Invalid credentials"}, status=401)
    if not check_password(str(payload["password"]), str(user["password_hash"])):
        return _json_response({"detail": "Invalid credentials"}, status=401)

    public_user = {key: value for key, value in user.items() if key != "password_hash"}
    return _json_response({"token": _issue_token(public_user), "user": public_user})


@require_http_methods(["POST"])
def logout(request):  # noqa: ANN001
    token_data = _decode_token_from_request(request)
    return _json_response({"detail": "Logged out", "token": token_data})


@require_http_methods(["POST"])
def pair_bracelet(request):  # noqa: ANN001
    try:
        payload = _parse_json(request)
    except ValueError as exc:
        return _json_response({"detail": str(exc)}, status=400)

    missing = _required(payload, ["user_id", "device_uid", "serial_number"])
    if missing:
        return _json_response({"detail": "Missing required fields", "missing": missing}, status=400)

    user_id = int(payload["user_id"])
    if not _ensure_user_exists(user_id):
        return _json_response({"detail": "User not found"}, status=404)

    now = timezone.now().isoformat()
    existing = _get_bracelet_by_identifier(str(payload["device_uid"]), str(payload["serial_number"]))
    if existing is not None and existing["user_id"] not in (None, user_id):
        return _json_response({"detail": "Bracelet already paired to another user"}, status=409)

    with transaction.atomic():
        with connection.cursor() as cursor:
            if existing is None:
                cursor.execute(
                    """
                    INSERT INTO bracelets (
                        user_id, device_uid, serial_number, display_name, firmware_version,
                        mac_address, status, paired_at, last_seen_at, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, user_id, device_uid, serial_number, display_name, firmware_version,
                              mac_address, status, paired_at, last_seen_at, created_at, updated_at
                    """,
                    [
                        user_id,
                        payload["device_uid"],
                        payload["serial_number"],
                        payload.get("display_name", "Bracelet de test"),
                        payload.get("firmware_version"),
                        payload.get("mac_address"),
                        payload.get("status", "active"),
                        now,
                        now,
                        now,
                        now,
                    ],
                )
            else:
                cursor.execute(
                    """
                    UPDATE bracelets
                    SET user_id = %s,
                        serial_number = %s,
                        display_name = %s,
                        firmware_version = %s,
                        mac_address = %s,
                        status = %s,
                        paired_at = COALESCE(paired_at, %s),
                        updated_at = %s
                    WHERE id = %s
                    RETURNING id, user_id, device_uid, serial_number, display_name, firmware_version,
                              mac_address, status, paired_at, last_seen_at, created_at, updated_at
                    """,
                    [
                        user_id,
                        payload["serial_number"],
                        payload.get("display_name", "Bracelet de test"),
                        payload.get("firmware_version"),
                        payload.get("mac_address"),
                        payload.get("status", "active"),
                        now,
                        now,
                        existing["id"],
                    ],
                )
            row = cursor.fetchone()

    if row is None:
        return _json_response({"detail": "Unable to pair bracelet"}, status=500)
    return _json_response({"bracelet": _row_to_bracelet(row)}, status=201 if existing is None else 200)


@require_http_methods(["GET"])
def list_bracelets(request, user_id: int):  # noqa: ANN001
    if not _ensure_user_exists(user_id):
        return _json_response({"detail": "User not found"}, status=404)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, user_id, device_uid, serial_number, display_name, firmware_version,
                   mac_address, status, paired_at, last_seen_at, created_at, updated_at
            FROM bracelets
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            [user_id],
        )
        bracelets = [_row_to_bracelet(row) for row in cursor.fetchall()]
    return _json_response({"bracelets": bracelets})


@require_http_methods(["POST"])
def datas_collection(request):  # noqa: ANN001
    try:
        payload = _parse_json(request)
    except ValueError as exc:
        return _json_response({"detail": str(exc)}, status=400)

    missing = _required(payload, ["device_uid", "serial_number"])
    if missing:
        return _json_response({"detail": "Missing required fields", "missing": missing}, status=400)

    with transaction.atomic():
        bracelet = _upsert_bracelet(payload)
        measurement = _insert_measurement(int(bracelet["id"]), payload)

    return _json_response({"bracelet": bracelet, "measurement": measurement}, status=201)


@require_http_methods(["GET"])
def datas_by_user(request, user_id: int):  # noqa: ANN001
    if not _ensure_user_exists(user_id):
        return _json_response({"detail": "User not found"}, status=404)

    limit = int(request.GET.get("limit", "100"))
    limit = max(1, min(limit, 500))
    offset = max(0, int(request.GET.get("offset", "0")))

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT m.id, m.bracelet_id, m.captured_at, m.heart_rate_bpm, m.spo2_percent,
                   m.step_count, m.motion_level, m.signal_quality, m.raw_payload,
                   m.source_topic, m.received_at, m.created_at,
                   b.device_uid, b.serial_number, b.display_name
            FROM biometrics_measurements m
            INNER JOIN bracelets b ON b.id = m.bracelet_id
            WHERE b.user_id = %s
            ORDER BY m.captured_at DESC
            LIMIT %s OFFSET %s
            """,
            [user_id, limit, offset],
        )
        datas = [
            {
                "id": row[0],
                "bracelet_id": row[1],
                "captured_at": row[2],
                "heart_rate_bpm": row[3],
                "spo2_percent": row[4],
                "step_count": row[5],
                "motion_level": row[6],
                "signal_quality": row[7],
                "raw_payload": row[8],
                "source_topic": row[9],
                "received_at": row[10],
                "created_at": row[11],
                "bracelet": {
                    "device_uid": row[12],
                    "serial_number": row[13],
                    "display_name": row[14],
                },
            }
            for row in cursor.fetchall()
        ]
    return _json_response({"user_id": user_id, "count": len(datas), "datas": datas})


@require_http_methods(["GET"])
def statistics_by_user(request, user_id: int):  # noqa: ANN001
    if not _ensure_user_exists(user_id):
        return _json_response({"detail": "User not found"}, status=404)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                COUNT(*) AS measurements_count,
                AVG(heart_rate_bpm) AS avg_heart_rate_bpm,
                MIN(heart_rate_bpm) AS min_heart_rate_bpm,
                MAX(heart_rate_bpm) AS max_heart_rate_bpm,
                AVG(spo2_percent) AS avg_spo2_percent,
                MAX(step_count) AS max_step_count,
                MAX(captured_at) AS last_measurement_at
            FROM biometrics_measurements
            WHERE bracelet_id IN (
                SELECT id
                FROM bracelets
                WHERE user_id = %s
            )
            """,
            [user_id],
        )
        row = cursor.fetchone()

    statistics = {
        "measurements_count": int(row[0] or 0),
        "avg_heart_rate_bpm": float(row[1]) if row[1] is not None else None,
        "min_heart_rate_bpm": int(row[2]) if row[2] is not None else None,
        "max_heart_rate_bpm": int(row[3]) if row[3] is not None else None,
        "avg_spo2_percent": float(row[4]) if row[4] is not None else None,
        "max_step_count": int(row[5] or 0),
        "last_measurement_at": row[6],
    }
    return _json_response({"user_id": user_id, "statistics": statistics})

