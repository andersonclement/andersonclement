import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
SQLALCHEMY_DATABASE_URI = os.environ.get(
    "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'smarttrader.db')}"
)
SQLALCHEMY_TRACK_MODIFICATIONS = False

ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")

ADMIN_CODE = os.environ.get("ADMIN_CODE", "admin7cas2024")
