"""Password hashing and JWT token handling."""
from datetime import datetime, timedelta, timezone
import bcrypt
import jwt

from app.core.config import get_settings

settings = get_settings()


def hash_password(password: str) -> str:
    """Return a bcrypt hash. Salt is generated and embedded automatically."""
    pwd_bytes = password.encode("utf-8")[:72]
    hashed_bytes = bcrypt.hashpw(pwd_bytes, bcrypt.gensalt())
    return hashed_bytes.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time comparison using bcrypt."""
    plain_bytes = plain.encode("utf-8")[:72]
    hashed_bytes = hashed.encode("utf-8")
    try:
        return bcrypt.checkpw(plain_bytes, hashed_bytes)
    except Exception:
        return False


def create_access_token(subject: str | int) -> str:
    """Build a JWT with sub and exp, signed with the configured secret."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": str(subject), "exp": expire}
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> str:
    """Return the subject. Raise on bad signature, bad algorithm, or expiry."""
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.ALGORITHM])
    sub = payload.get("sub")
    if sub is None:
        raise jwt.PyJWTError("Subject ('sub') missing in token payload")
    return str(sub)