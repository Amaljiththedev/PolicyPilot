"""Encrypt secrets we must store (Drive refresh tokens) with a Fernet key from the environment.

Generate a key once:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from cryptography.fernet import Fernet

from app.core.config import get_settings


class MissingKey(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_settings().TOKEN_ENCRYPTION_KEY
    if not key:
        raise MissingKey("TOKEN_ENCRYPTION_KEY is not set")
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
