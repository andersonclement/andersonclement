import base64
import os

from cryptography.fernet import Fernet


def get_or_create_key():
    key_path = os.path.join(os.path.dirname(__file__), ".encryption_key")
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    with open(key_path, "wb") as f:
        f.write(key)
    os.chmod(key_path, 0o600)
    return key


_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is None:
        from config import ENCRYPTION_KEY
        if ENCRYPTION_KEY:
            key = base64.urlsafe_b64encode(
                ENCRYPTION_KEY.encode().ljust(32, b"\0")[:32]
            )
        else:
            key = get_or_create_key()
        _fernet = Fernet(key)
    return _fernet


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
