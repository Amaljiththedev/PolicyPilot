import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://policypilot:policypilot@localhost:5432/policypilot"

    # API Keys
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None

    # RAG Configuration
    CHUNK_SIZE: int = 1000
    TOP_K: int = 5

    # Security
    JWT_SECRET: str = "supersecretjwtkey_change_in_production"

    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
