from datetime import datetime, timedelta, timezone
import pytest
import jwt

from app.core.config import get_settings
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)

settings = get_settings()


def test_hash_password_and_verify_success():
    plain_password = "MySecurePassword123!"
    hashed = hash_password(plain_password)

    # Hash should be non-empty string and not equal to plain password
    assert isinstance(hashed, str)
    assert hashed != plain_password
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")

    # Correct password verification
    assert verify_password(plain_password, hashed) is True


def test_verify_password_wrong_password():
    plain_password = "MySecurePassword123!"
    hashed = hash_password(plain_password)

    # Incorrect password should return False
    assert verify_password("WrongPassword456!", hashed) is False


def test_jwt_create_and_decode_token():
    subject = "user_123"
    token = create_access_token(subject)

    assert isinstance(token, str)
    assert len(token) > 0

    decoded_sub = decode_access_token(token)
    assert decoded_sub == "user_123"


def test_jwt_decode_invalid_token():
    invalid_token = "invalid.jwt.token.string"

    with pytest.raises(jwt.PyJWTError):
        decode_access_token(invalid_token)


def test_jwt_decode_expired_token():
    # Build an expired token manually
    expired_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    payload = {"sub": "user_expired", "exp": expired_time}
    expired_token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.ALGORITHM)

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired_token)
