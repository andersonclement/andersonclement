import os

from cryptography.fernet import Fernet

_KEY_PATH = os.path.join(os.path.dirname(__file__), "data", ".encryption_key")
_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet

    env_key = os.environ.get("ENCRYPTION_KEY", "")
    if env_key:
        if len(env_key) == 44 and env_key.endswith("="):
            key = env_key.encode()
        else:
            raise ValueError(
                "ENCRYPTION_KEY must be a valid 44-char Fernet key. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
    elif os.path.exists(_KEY_PATH):
        with open(_KEY_PATH, "rb") as f:
            key = f.read().strip()
    else:
        key = Fernet.generate_key()
        os.makedirs(os.path.dirname(_KEY_PATH), exist_ok=True)
        fd = os.open(_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)

    _fernet = Fernet(key)
    return _fernet


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
