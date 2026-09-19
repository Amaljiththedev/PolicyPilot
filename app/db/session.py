from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    echo=False,  # Set to True to see SQL queries
    pool_pre_ping=True,  # Test connections before using them
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Session:
    """Dependency injection for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()