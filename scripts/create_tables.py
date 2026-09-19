import os
import sys
import logging

# Ensure project root directory is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.db.base import Base
from app.db.session import engine
from app.db import models  # Ensure models are imported for metadata reflection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("create_tables")


def create_tables():
    """Enable pgvector extension and create all SQLAlchemy declarative tables."""
    logger.info("Connecting to database and enabling vector extension...")
    with engine.connect() as connection:
        try:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            connection.commit()
            logger.info("pgvector extension enabled successfully.")
        except Exception as e:
            logger.warning(f"Could not enable pgvector extension (non-PostgreSQL or insufficient permissions): {e}")

    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("All tables created successfully!")


if __name__ == "__main__":
    create_tables()
