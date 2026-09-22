import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api.deps import get_db
from app.db.base import Base
from app.db.models import User
from app.core.security import hash_password

# Use an in-memory SQLite database for fast isolated route testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_register_user_success():
    payload = {
        "email": "newstaff@example.com",
        "password": "Password123!",
        "full_name": "New Staff Member"
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newstaff@example.com"
    assert data["full_name"] == "New Staff Member"
    assert data["role"] == "staff"  # Verified default role is staff, not admin
    assert "id" in data


def test_register_user_duplicate_email():
    payload = {
        "email": "duplicate@example.com",
        "password": "Password123!",
        "full_name": "First User"
    }
    # Register once
    res1 = client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    # Attempt duplicate registration
    res2 = client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 400
    assert "already exists" in res2.json()["detail"]


def test_login_staff_user_success():
    # Register staff user
    reg_payload = {
        "email": "staffuser@example.com",
        "password": "StaffPassword123!",
        "full_name": "Staff User"
    }
    client.post("/api/v1/auth/register", json=reg_payload)

    # Login
    login_payload = {
        "email": "staffuser@example.com",
        "password": "StaffPassword123!"
    }
    response = client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["role"] == "staff"


def test_login_admin_user_success():
    # Pre-seed an admin user directly into DB
    db = TestingSessionLocal()
    admin_user = User(
        email="admin@example.com",
        hashed_password=hash_password("AdminPassword123!"),
        full_name="Admin User",
        role="admin",
        is_active=True
    )
    db.add(admin_user)
    db.commit()
    db.close()

    # Login as admin
    login_payload = {
        "email": "admin@example.com",
        "password": "AdminPassword123!"
    }
    response = client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["user"]["role"] == "admin"


def test_login_invalid_password():
    reg_payload = {
        "email": "user@example.com",
        "password": "CorrectPassword123!"
    }
    client.post("/api/v1/auth/register", json=reg_payload)

    login_payload = {
        "email": "user@example.com",
        "password": "WrongPassword456!"
    }
    response = client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 401
    assert "Incorrect email or password" in response.json()["detail"]


def test_get_me_authenticated():
    # Register and login
    reg_payload = {
        "email": "me_test@example.com",
        "password": "Password123!",
        "full_name": "Me Tester"
    }
    client.post("/api/v1/auth/register", json=reg_payload)

    login_res = client.post("/api/v1/auth/login", json={
        "email": "me_test@example.com",
        "password": "Password123!"
    })
    token = login_res.json()["access_token"]

    # Call GET /me
    headers = {"Authorization": f"Bearer {token}"}
    me_res = client.get("/api/v1/auth/me", headers=headers)
    assert me_res.status_code == 200
    data = me_res.json()
    assert data["email"] == "me_test@example.com"
    assert data["full_name"] == "Me Tester"
    assert data["role"] == "staff"
