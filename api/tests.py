from __future__ import annotations

import bcrypt
from django.db import connection
from django.test import TestCase
from django.utils import timezone


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
			CREATE TABLE IF NOT EXISTS bracelets (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				user_id INTEGER UNIQUE,
				device_uid TEXT NOT NULL UNIQUE,
				serial_number TEXT NOT NULL UNIQUE,
				display_name TEXT NOT NULL,
				firmware_version TEXT,
				mac_address TEXT,
				status TEXT NOT NULL DEFAULT 'active',
				paired_at TEXT,
				last_seen_at TEXT,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL,
				FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
			)
			"""
		)
		cursor.execute(
			"""
			CREATE TABLE IF NOT EXISTS biometrics_measurements (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				bracelet_id INTEGER NOT NULL,
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
				FOREIGN KEY(bracelet_id) REFERENCES bracelets(id) ON DELETE CASCADE
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

	def test_pair_datas_and_statistics(self):
		self.client.post(
			"/api/register",
			data='{"email":"user@example.com","username":"user","password":"secret"}',
			content_type="application/json",
		)
		pair_response = self.client.post(
			"/api/bracelets/pair",
			data=(
				'{"user_id":1,"device_uid":"11111111-1111-1111-1111-111111111111",'
				'"serial_number":"BR-001","display_name":"Bracelet test"}'
			),
			content_type="application/json",
		)
		self.assertEqual(pair_response.status_code, 201)

		datas_response = self.client.post(
			"/api/datas",
			data=(
				'{"device_uid":"11111111-1111-1111-1111-111111111111",'
				'"serial_number":"BR-001","display_name":"Bracelet test",'
				'"captured_at":"2026-08-08T10:00:00Z","heart_rate_bpm":72,'
				'"spo2_percent":98.2,"step_count":12,"motion_level":0.45,'
				'"signal_quality":90,"source_topic":"api/test",'
				'"raw_payload":{"sequence":1}}'
			),
			content_type="application/json",
		)
		self.assertEqual(datas_response.status_code, 201)

		list_response = self.client.get("/api/datas/1")
		self.assertEqual(list_response.status_code, 200)
		self.assertEqual(list_response.json()["count"], 1)

		statistics_response = self.client.get("/api/statistics/1")
		self.assertEqual(statistics_response.status_code, 200)
		self.assertEqual(statistics_response.json()["statistics"]["measurements_count"], 1)
