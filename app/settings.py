"""
Django settings for the API backend.
"""

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-pdg-backend-dev-key")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "*").split(",") if host.strip()]

# --- HTTPS derrière un reverse proxy (Caddy) --------------------------------
# Le proxy termine le TLS et transmet le protocole d'origine dans un en-tête.
# Format attendu : "HTTP_X_FORWARDED_PROTO,https".
_ssl_header = os.getenv("SECURE_PROXY_SSL_HEADER", "").strip()
if _ssl_header and "," in _ssl_header:
    _name, _value = (part.strip() for part in _ssl_header.split(",", 1))
    SECURE_PROXY_SSL_HEADER = (_name, _value)

# HSTS : 0 = désactivé. Passer à 31536000 une fois le HTTPS stable.
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
if SECURE_HSTS_SECONDS:
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

INSTALLED_APPS = [
    "corsheaders",
    "api",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8080,http://127.0.0.1:8080,"
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

ROOT_URLCONF = "app.urls"
WSGI_APPLICATION = "app.wsgi.application"

def _database_config() -> dict[str, object]:
    db_host = os.getenv("DB_HOST")
    if not db_host:
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "bracelet_connecte"),
        "USER": os.getenv("DB_USER", "bracelet"),
        "PASSWORD": os.getenv("DB_PASSWORD", "bracelet"),
        "HOST": db_host,
        "PORT": os.getenv("DB_PORT", "5432"),
        "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "0")),
    }


DATABASES = {"default": _database_config()}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
