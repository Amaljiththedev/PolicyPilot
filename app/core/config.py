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
    CHUNK_OVERLAP: int = 200
    CHUNK_STRATEGY: str = "recursive"
    TOP_K: int = 5
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIMENSION: int = 384
    EMBEDDING_BATCH_SIZE: int = 32
    EMBEDDING_QUERY_PREFIX: str = (
        "Represent this sentence for searching relevant passages: "
    )
    HNSW_M: int = 16
    HNSW_EF_CONSTRUCTION: int = 64
    # LLM (any OpenAI-compatible provider: Cerebras, Groq, Mistral, Ollama)
    LLM_BASE_URL: str = "https://api.cerebras.ai/v1"
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gpt-oss-120b"
    LLM_MIN_INTERVAL: float = 0.0


    # Security
    JWT_SECRET: str = "supersecretjwtkey_change_in_production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Reranking
    RERANK_ENABLED: bool = False
    RERANK_STRATEGY: str = "cross"      # cross | llm_point | llm_list
    RERANK_CANDIDATES: int = 20
    RERANK_MODEL: str = "BAAI/bge-reranker-base"
    LLM_RERANK_CANDIDATES: int = 10
    LLM_NO_THINK: bool = True           # appends /no_think for Qwen3 models


    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def database_url(self) -> str:
        return self.DATABASE_URL



settings = Settings()


def get_settings() -> Settings:
    return settings


