from __future__ import annotations

import codecs

import bcrypt
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from api.views import MEASUREMENT_EXPORT_FIELDS


def _create_schema() -> None:
	with connection.cursor() as cursor:
		cursor.execute(
			"""
			CREATE TABLE IF NOT EXISTS users (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				email TEXT NOT NULL UNIQUE,
				username TEXT NOT NULL UNIQUE,
				password_hash TEXT,
				first_name TEXT NOT NULL DEFAULT '',
				last_name TEXT NOT NULL DEFAULT '',
				is_active BOOLEAN NOT NULL DEFAULT 1,
				is_staff BOOLEAN NOT NULL DEFAULT 0,
				is_superuser BOOLEAN NOT NULL DEFAULT 0,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)
			"""
		)
		cursor.execute(
			"""
			CREATE TABLE IF NOT EXISTS biometrics_measurements (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				user_id INTEGER NOT NULL,
				device_uid TEXT,
				serial_number TEXT,
				display_name TEXT,
				mac_address TEXT,
				captured_at TEXT NOT NULL,
				heart_rate_bpm INTEGER,
				spo2_percent NUMERIC(5, 2),
				step_count INTEGER NOT NULL DEFAULT 0,
				motion_level NUMERIC(8, 3),
				signal_quality INTEGER,
				raw_payload TEXT,
				source_topic TEXT,
				received_at TEXT NOT NULL,
				created_at TEXT NOT NULL,
				FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
			)
			"""
		)


class BackendApiTests(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_create_schema()

	def test_register_login_and_logout(self):
		register_response = self.client.post(
			"/api/register",
			data='{"email":"demo@example.com","username":"demo","password":"secret"}',
			content_type="application/json",
		)
		self.assertEqual(register_response.status_code, 201)

		login_response = self.client.post(
			"/api/login",
			data='{"email":"demo@example.com","password":"secret"}',
			content_type="application/json",
		)
		self.assertEqual(login_response.status_code, 200)
		self.assertIn("token", login_response.json())

		logout_response = self.client.post(
			"/api/logout",
			HTTP_AUTHORIZATION=f"Bearer {login_response.json()['token']}",
		)
		self.assertEqual(logout_response.status_code, 200)

	def test_me_requires_valid_token(self):
		register_response = self.client.post(
			"/api/register",
			data='{"email":"me@example.com","username":"me","password":"secret"}',
			content_type="application/json",
		)
		token = register_response.json()["user"]["token"]

		unauthenticated_response = self.client.get("/api/me")
		self.assertEqual(unauthenticated_response.status_code, 401)

		authenticated_response = self.client.get("/api/me", HTTP_AUTHORIZATION=f"Bearer {token}")
		self.assertEqual(authenticated_response.status_code, 200)
		self.assertEqual(authenticated_response.json()["user"]["email"], "me@example.com")

		garbage_token_response = self.client.get("/api/me", HTTP_AUTHORIZATION="Bearer not-a-real-token")
		self.assertEqual(garbage_token_response.status_code, 401)

	def test_login_accepts_raw_bcrypt_hash_from_db_seed(self):
		# infra-db seeds demo accounts via Postgres pgcrypto's crypt()/gen_salt('bf'),
		# which writes a raw "$2b$..." bcrypt hash with no algorithm prefix — a format
		# Django's own check_password() does not recognize. Insert a user the same way
		# (bypassing /api/register, which would hash with Django's PBKDF2 instead) to
		# make sure /api/login still authenticates them.
		raw_hash = bcrypt.hashpw(b"demo1234", bcrypt.gensalt(rounds=4)).decode("ascii")
		now = timezone.now().isoformat()
		with connection.cursor() as cursor:
			cursor.execute(
				"""
				INSERT INTO users (
					email, username, password_hash, first_name, last_name,
					is_active, is_staff, is_superuser, created_at, updated_at
				) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
				""",
				["seed@example.com", "seeduser", raw_hash, "Seed", "User", True, False, False, now, now],
			)

		login_response = self.client.post(
			"/api/login",
			data='{"email":"seed@example.com","password":"demo1234"}',
			content_type="application/json",
		)
		self.assertEqual(login_response.status_code, 200)
		self.assertIn("token", login_response.json())

	def test_datas_requires_auth(self):
		# There is no pairing step any more: POST /api/datas attaches the
		# measurement to whoever the Bearer token belongs to, so a request
		# without one (or with an invalid one) must be rejected outright —
		# otherwise anyone could post data to any device_uid/serial_number.
		unauthenticated_response = self.client.post(
			"/api/datas",
			data='{"device_uid":"11111111-1111-1111-1111-111111111111","serial_number":"BR-001"}',
			content_type="application/json",
		)
		self.assertEqual(unauthenticated_response.status_code, 401)

	def test_post_datas_and_read_back_datas_and_statistics(self):
		register_response = self.client.post(
			"/api/register",
			data='{"email":"user@example.com","username":"user","password":"secret"}',
			content_type="application/json",
		)
		token = register_response.json()["user"]["token"]
		user_id = register_response.json()["user"]["id"]

		datas_response = self.client.post(
			"/api/datas",
			data=(
				'{"device_uid":"11111111-1111-1111-1111-111111111111",'
				'"serial_number":"BR-001","display_name":"Bracelet test",'
				'"captured_at":"2026-08-08T10:00:00Z","heart_rate_bpm":72,'
				'"spo2_percent":98.2,"step_count":12,"motion_level":0.45,'
				'"signal_quality":90,"source_topic":"api/test"}'
			),
			content_type="application/json",
			HTTP_AUTHORIZATION=f"Bearer {token}",
		)
		self.assertEqual(datas_response.status_code, 201)
		self.assertEqual(datas_response.json()["measurement"]["bracelet"]["serial_number"], "BR-001")

		list_response = self.client.get(f"/api/datas/{user_id}")
		self.assertEqual(list_response.status_code, 200)
		self.assertEqual(list_response.json()["count"], 1)

		statistics_response = self.client.get(f"/api/statistics/{user_id}")
		self.assertEqual(statistics_response.status_code, 200)
		self.assertEqual(statistics_response.json()["statistics"]["measurements_count"], 1)

	def test_a_user_can_post_from_several_different_bracelets(self):
		# The whole point of dropping the bracelets table: no pairing means no
		# "one bracelet per account" limit either. Two different device_uid /
		# serial_number values, same token, both land on the same user.
		register_response = self.client.post(
			"/api/register",
			data='{"email":"multi@example.com","username":"multi","password":"secret"}',
			content_type="application/json",
		)
		token = register_response.json()["user"]["token"]
		user_id = register_response.json()["user"]["id"]

		for device_uid, serial_number in (
			("11111111-1111-1111-1111-111111111111", "BR-A"),
			("22222222-2222-2222-2222-222222222222", "BR-B"),
		):
			response = self.client.post(
				"/api/datas",
				data=f'{{"device_uid":"{device_uid}","serial_number":"{serial_number}","step_count":1}}',
				content_type="application/json",
				HTTP_AUTHORIZATION=f"Bearer {token}",
			)
			self.assertEqual(response.status_code, 201)

		list_response = self.client.get(f"/api/datas/{user_id}")
		self.assertEqual(list_response.json()["count"], 2)

	def test_delete_my_data_requires_auth(self):
		unauthenticated_response = self.client.delete("/api/me/data")
		self.assertEqual(unauthenticated_response.status_code, 401)

	def test_delete_my_data_wipes_measurements_but_keeps_account(self):
		register_response = self.client.post(
			"/api/register",
			data='{"email":"wipe@example.com","username":"wipe","password":"secret"}',
			content_type="application/json",
		)
		token = register_response.json()["user"]["token"]
		user_id = register_response.json()["user"]["id"]

		self.client.post(
			"/api/datas",
			data=(
				'{"device_uid":"22222222-2222-2222-2222-222222222222",'
				'"serial_number":"BR-002","display_name":"Bracelet wipe",'
				'"captured_at":"2026-08-08T10:00:00Z","heart_rate_bpm":80,'
				'"step_count":5}'
			),
			content_type="application/json",
			HTTP_AUTHORIZATION=f"Bearer {token}",
		)

		delete_response = self.client.delete("/api/me/data", HTTP_AUTHORIZATION=f"Bearer {token}")
		self.assertEqual(delete_response.status_code, 200)
		self.assertEqual(delete_response.json()["deleted_measurements"], 1)

		datas_response = self.client.get(f"/api/datas/{user_id}")
		self.assertEqual(datas_response.json()["count"], 0)

		me_response = self.client.get("/api/me", HTTP_AUTHORIZATION=f"Bearer {token}")
		self.assertEqual(me_response.status_code, 200)
		self.assertEqual(me_response.json()["user"]["email"], "wipe@example.com")

	def test_export_my_data_requires_auth(self):
		unauthenticated_response = self.client.get("/api/me/data/export")
		self.assertEqual(unauthenticated_response.status_code, 401)

	def test_export_my_data_json_and_csv(self):
		register_response = self.client.post(
			"/api/register",
			data='{"email":"export@example.com","username":"export","password":"secret"}',
			content_type="application/json",
		)
		token = register_response.json()["user"]["token"]

		self.client.post(
			"/api/datas",
			data=(
				'{"device_uid":"33333333-3333-3333-3333-333333333333",'
				'"serial_number":"BR-003","display_name":"Bracelet export",'
				'"captured_at":"2026-08-08T10:00:00Z","heart_rate_bpm":90,'
				'"step_count":42}'
			),
			content_type="application/json",
			HTTP_AUTHORIZATION=f"Bearer {token}",
		)

		json_response = self.client.get("/api/me/data/export", HTTP_AUTHORIZATION=f"Bearer {token}")
		self.assertEqual(json_response.status_code, 200)
		payload = json_response.json()
		self.assertEqual(payload["user"]["email"], "export@example.com")
		self.assertEqual(len(payload["measurements"]), 1)
		measurement = payload["measurements"][0]
		self.assertEqual(measurement["heart_rate_bpm"], 90)
		self.assertEqual(measurement["bracelet_serial_number"], "BR-003")

		csv_response = self.client.get(
			"/api/me/data/export?format=csv", HTTP_AUTHORIZATION=f"Bearer {token}"
		)
		self.assertEqual(csv_response.status_code, 200)
		self.assertEqual(csv_response["Content-Type"], "text/csv; charset=utf-8")
		body = csv_response.content.decode("utf-8-sig")
		header_row = body.splitlines()[0]
		# Séparateur ';' requis pour qu'Excel (localisation FR) ouvre bien le fichier en colonnes.
		self.assertEqual(header_row.split(";"), MEASUREMENT_EXPORT_FIELDS)
		data_row = body.splitlines()[1].split(";")
		self.assertEqual(data_row[MEASUREMENT_EXPORT_FIELDS.index("heart_rate_bpm")], "90")
		self.assertEqual(data_row[MEASUREMENT_EXPORT_FIELDS.index("bracelet_serial_number")], "BR-003")
		self.assertTrue(csv_response.content.startswith(codecs.BOM_UTF8))

		invalid_format_response = self.client.get(
			"/api/me/data/export?format=xml", HTTP_AUTHORIZATION=f"Bearer {token}"
		)
		self.assertEqual(invalid_format_response.status_code, 400)
