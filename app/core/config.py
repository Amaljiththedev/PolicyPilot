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

    # First-stage search: vector | keyword | hybrid
    SEARCH_MODE: str = "vector"
    HYBRID_CANDIDATES: int = 30        # per retriever, before RRF

    # Sign-in (Google). Password login is off unless PASSWORD_LOGIN_ENABLED=true.
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"
    GOOGLE_ALLOWED_DOMAINS: str = ""        # e.g. "liverpool.ac.uk,gmail.com"; empty = any verified Google account
    ADMIN_EMAILS: str = ""                  # comma-separated; these accounts get role=admin on first sign-in
    PASSWORD_LOGIN_ENABLED: bool = False

    # Google Drive sync
    TOKEN_ENCRYPTION_KEY: Optional[str] = None   # Fernet key; encrypts stored Drive refresh tokens
    DRIVE_SYNC_INTERVAL_SECONDS: int = 900

    # Slack bot (Socket Mode: no public URL needed)
    SLACK_BOT_TOKEN: Optional[str] = None        # xoxb-...
    SLACK_APP_TOKEN: Optional[str] = None        # xapp-... (connections:write)
    SLACK_ESCALATION_USER_ID: Optional[str] = None   # e.g. U0123 (HR contact) tagged when the bot can't answer
    SLACK_DEFAULT_ORGANISATION: Optional[str] = None

    # MCP server
    MCP_USER_EMAIL: str = "mcp@policypilot.local"   # queries asked through MCP are logged as this user

    # Answering (Phase 8)
    ANSWER_TOP_K: int = 5
    ANSWER_NEIGHBOURS: int = 1          # also show the LLM the chunk before/after each hit
    ANSWER_PROMPT: str = "v2"          # v1 | v2, see answer.py
    JUDGE_MODEL: str = "qwen/qwen3-32b"   # eval judge: a different model from the answerer

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


