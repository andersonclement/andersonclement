import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ENV = os.environ.get("FLASK_ENV", "production")

_env_secret = os.environ.get("SECRET_KEY", "")
if ENV == "production" and not _env_secret:
    raise RuntimeError(
        "SECRET_KEY must be set in production. "
        "Generate one: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
SECRET_KEY = _env_secret or secrets.token_hex(32)
SQLALCHEMY_DATABASE_URI = os.environ.get(
    "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'data', 'smarttrader.db')}"
)
SQLALCHEMY_TRACK_MODIFICATIONS = False

ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

METAAPI_TOKEN = os.environ.get("METAAPI_TOKEN", "")

SESSION_COOKIE_SECURE = ENV == "production"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
PERMANENT_SESSION_LIFETIME = 3600 * 8

WTF_CSRF_ENABLED = True
WTF_CSRF_TIME_LIMIT = 3600

RATELIMIT_DEFAULT = "200 per hour"
RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
