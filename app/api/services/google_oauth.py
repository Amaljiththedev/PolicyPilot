"""Google OAuth 2.0 (authorization-code flow), used for sign-in and for connecting Drive.

Both flows share one redirect URI. The `state` parameter is a short-lived signed JWT that
says which flow it is (and, for Drive, which user), so a callback can't be forged or replayed
into the wrong flow.
"""
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import User

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
LOGIN_SCOPES = "openid email profile"
DRIVE_SCOPES = "openid email https://www.googleapis.com/auth/drive.readonly"


class GoogleAuthError(Exception):
    """Anything that should become a 400/401/403 for the caller."""
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


def _s():
    return get_settings()


def configured() -> bool:
    s = _s()
    return bool(s.GOOGLE_CLIENT_ID and s.GOOGLE_CLIENT_SECRET)


# ---------- state ----------
def make_state(purpose: str, **extra) -> str:
    payload = {"purpose": purpose, "nonce": secrets.token_urlsafe(8),
               "exp": datetime.now(timezone.utc) + timedelta(minutes=10), **extra}
    return jwt.encode(payload, _s().JWT_SECRET, algorithm=_s().ALGORITHM)


def read_state(state: str) -> dict:
    try:
        return jwt.decode(state, _s().JWT_SECRET, algorithms=[_s().ALGORITHM])
    except jwt.PyJWTError as e:
        raise GoogleAuthError(f"invalid or expired state: {e}", 400)


# ---------- URLs and token exchange ----------
def authorization_url(purpose: str, **extra) -> str:
    s = _s()
    params = {"client_id": s.GOOGLE_CLIENT_ID, "redirect_uri": s.GOOGLE_REDIRECT_URI,
              "response_type": "code", "state": make_state(purpose, **extra)}
    if purpose == "drive":
        # offline + consent = Google returns a refresh token, so sync can run without the user
        params.update(scope=DRIVE_SCOPES, access_type="offline", prompt="consent",
                      include_granted_scopes="true")
    else:
        params.update(scope=LOGIN_SCOPES, prompt="select_account")
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str, http: httpx.Client | None = None) -> dict:
    s = _s()
    client = http or httpx.Client(timeout=15)
    r = client.post(TOKEN_URL, data={"code": code, "client_id": s.GOOGLE_CLIENT_ID,
                                     "client_secret": s.GOOGLE_CLIENT_SECRET,
                                     "redirect_uri": s.GOOGLE_REDIRECT_URI,
                                     "grant_type": "authorization_code"})
    if r.status_code != 200:
        raise GoogleAuthError(f"Google rejected the code: {r.text[:200]}", 400)
    return r.json()


def verify_id_token(token: str) -> dict:
    """Checks signature (Google's public keys), audience = our client id, expiry and issuer."""
    try:
        claims = google_id_token.verify_oauth2_token(token, google_requests.Request(), _s().GOOGLE_CLIENT_ID)
    except ValueError as e:
        raise GoogleAuthError(f"invalid Google ID token: {e}")
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise GoogleAuthError("wrong issuer")
    return claims


# ---------- who is allowed in ----------
def _csv(value: str) -> set[str]:
    return {x.strip().lower() for x in (value or "").split(",") if x.strip()}


def user_from_google(db: Session, claims: dict) -> User:
    """Find or create the user for a verified Google identity, enforcing the domain allow-list."""
    email = (claims.get("email") or "").lower()
    if not email or not claims.get("email_verified"):
        raise GoogleAuthError("Google account has no verified email", 403)
    allowed = _csv(_s().GOOGLE_ALLOWED_DOMAINS)
    if allowed and email.rsplit("@", 1)[-1] not in allowed:
        raise GoogleAuthError(f"accounts from {email.rsplit('@', 1)[-1]} are not allowed", 403)

    sub = str(claims["sub"])
    user = db.query(User).filter(User.google_sub == sub).first()
    if user is None:
        user = db.query(User).filter(User.email == email).first()
        if user is not None:                   # existing account, first Google sign-in: link it
            user.google_sub = sub
    if user is None:
        user = User(email=email, full_name=claims.get("name"), google_sub=sub,
                    auth_provider="google", hashed_password=None, is_active=True,
                    role="admin" if email in _csv(_s().ADMIN_EMAILS) else "staff")
        db.add(user)
    if not user.is_active:
        raise GoogleAuthError("account is disabled", 403)
    db.commit()
    db.refresh(user)
    return user
