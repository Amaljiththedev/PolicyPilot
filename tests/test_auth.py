import pytest
import jwt
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import get_current_user, require_admin_user
from app.core.security import create_access_token, hash_password
from app.db.models import User


class MockQuery:
    def __init__(self, user_obj):
        self.user_obj = user_obj

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.user_obj


class MockDB:
    def __init__(self, user_obj=None):
        self.user_obj = user_obj

    def query(self, model):
        return MockQuery(self.user_obj)


def test_get_current_user_valid_token():
    user = User(
        id=1,
        email="test@example.com",
        hashed_password=hash_password("password123"),
        role="staff"
    )
    db = MockDB(user_obj=user)
    token = create_access_token(subject=user.id)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    current_user = get_current_user(creds=creds, db=db)
    assert current_user.id == 1
    assert current_user.email == "test@example.com"


def test_get_current_user_no_credentials():
    db = MockDB()
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(creds=None, db=db)

    assert exc_info.value.status_code == 401
    assert "Not authenticated" in exc_info.value.detail


def test_get_current_user_invalid_token():
    db = MockDB()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid.token.str")

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(creds=creds, db=db)

    assert exc_info.value.status_code == 401
    assert "Invalid authentication" in exc_info.value.detail


def test_get_current_user_user_not_found():
    db = MockDB(user_obj=None)
    token = create_access_token(subject=999)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(creds=creds, db=db)

    assert exc_info.value.status_code == 401
    assert "User not found" in exc_info.value.detail


def test_require_admin_user_success():
    admin_user = User(id=1, email="admin@example.com", role="admin")
    result = require_admin_user(user=admin_user)
    assert result.role == "admin"


def test_require_admin_user_forbidden():
    staff_user = User(id=2, email="staff@example.com", role="staff")
    with pytest.raises(HTTPException) as exc_info:
        require_admin_user(user=staff_user)

    assert exc_info.value.status_code == 403
    assert "Insufficient permissions" in exc_info.value.detail
