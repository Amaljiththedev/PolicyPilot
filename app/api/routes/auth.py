from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.services import google_oauth as g
from app.core.config import get_settings

from app.api.deps import get_db, get_current_user
from app.core.security import hash_password, verify_password, create_access_token
from app.db.models import User
from app.schemas.auth import UserCreate, UserRead, LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


def _password_login_enabled():
    if not get_settings().PASSWORD_LOGIN_ENABLED:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "password sign-in is disabled; use /api/v1/auth/google/login")


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    _: None = Depends(_password_login_enabled),
):
    """Public user registration endpoint (always creates staff users, not admin)."""
    # Check if email is already registered
    existing_user = db.query(User).filter(User.email == user_in.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists."
        )

    # Hash password and save new staff user
    hashed_pwd = hash_password(user_in.password)
    new_user = User(
        email=user_in.email,
        hashed_password=hashed_pwd,
        full_name=user_in.full_name,
        role="staff",  # Default non-admin role
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


@router.post("/login", response_model=TokenResponse)
def login(
    login_in: LoginRequest,
    db: Session = Depends(get_db),
    _: None = Depends(_password_login_enabled),
):
    """Login endpoint for both staff and admin users. Issues a signed JWT access token."""
    user = db.query(User).filter(User.email == login_in.email).first()
    if not user or not verify_password(login_in.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account."
        )

    token = create_access_token(subject=user.id)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=user
    )


@router.get("/me", response_model=UserRead)
def get_me(
    current_user: User = Depends(get_current_user)
):
    """Get current authenticated user profile."""
    return current_user



# ---------------------------------------------------------------- Google sign-in
def _google_ready():
    if not g.configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Google sign-in is not configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)")


@router.get("/google/login", dependencies=[Depends(_google_ready)])
def google_login():
    """Open this in a browser: it redirects to Google's account chooser."""
    return RedirectResponse(g.authorization_url("login"), status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/google/callback", dependencies=[Depends(_google_ready)])
def google_callback(code: str | None = None, state: str | None = None, error: str | None = None,
                    db: Session = Depends(get_db)):
    """Google redirects here. Sign-in returns a PolicyPilot token; Drive connect stores the link."""
    if error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Google returned: {error}")
    if not code or not state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing code or state")
    try:
        st = g.read_state(state)
        tokens = g.exchange_code(code)
        claims = g.verify_id_token(tokens["id_token"])
        if st["purpose"] == "drive":
            from app.integrations.gdrive import save_connection
            conn = save_connection(db, st["user_id"], claims.get("email"), tokens.get("refresh_token"))
            return {"status": "drive connected", "connection_id": conn.id,
                    "next": f"POST /api/v1/drive/connections/{conn.id}/folder, then /sync"}
        user = g.user_from_google(db, claims)
    except g.GoogleAuthError as e:
        raise HTTPException(e.status_code, str(e))
    return TokenResponse(access_token=create_access_token(subject=user.id), token_type="bearer", user=user)


class GoogleIdToken(BaseModel):
    id_token: str


@router.post("/google/token", response_model=TokenResponse, dependencies=[Depends(_google_ready)])
def google_token(body: GoogleIdToken, db: Session = Depends(get_db)):
    """For front-ends using Google Identity Services: send the Google ID token, get a PolicyPilot token."""
    try:
        user = g.user_from_google(db, g.verify_id_token(body.id_token))
    except g.GoogleAuthError as e:
        raise HTTPException(e.status_code, str(e))
    return TokenResponse(access_token=create_access_token(subject=user.id), token_type="bearer", user=user)
