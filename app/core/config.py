"""Configuration and environment settings.
Governing spec: BE-15.
The ONLY module permitted to read environment variables.
"""

from enum import Enum
from typing import List, Optional
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # --- 4.1 Core ---
    APP_ENV: AppEnv = AppEnv.DEVELOPMENT
    APP_VERSION: str = "1.0.0"
    LOG_LEVEL: LogLevel = LogLevel.INFO
    PORT: int = 8000

    # --- 4.2 Database (PostgreSQL with Pgvector) ---
    DATABASE_URL: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/verity_db",
        description="PostgreSQL connection URI (Standard Postgres with pgvector)",
    )
    DB_POOL_MIN: int = Field(default=1, ge=1)
    DB_POOL_MAX: int = Field(default=5, le=5)
    DB_STATEMENT_CACHE_SIZE: int = 0
    EXPECTED_SCHEMA_VERSION: int = 1

    # --- 4.3 Storage (Local Filesystem / Volume) ---
    STORAGE_DIR: str = "./data/uploads"
    SUPABASE_URL: Optional[str] = None
    SUPABASE_SERVICE_KEY: Optional[str] = None
    SUPABASE_STORAGE_BUCKET: str = "documents"
    SUPABASE_JWKS_URL: Optional[str] = None

    # --- 4.4 Gemini ---
    GEMINI_API_KEY: str = Field(..., description="Google Gemini API Key")
    EMBEDDING_MODEL: str = "gemini-embedding-001"
    EMBEDDING_DIMENSIONS: int = 768
    GENERATION_MODEL: str = "gemini-3.6-flash"
    GENERATION_TEMPERATURE: float = Field(default=0.1, le=0.2)


    GENERATION_MAX_TOKENS: int = 2048
    EMBEDDING_BATCH_SIZE: int = 50
    GEMINI_RPM: int = 12
    GEMINI_MAX_RETRIES: int = 5
    DAILY_QUOTA_CEILING: int = 1200

    # --- 4.5 Chunking (LlamaIndex Token Utilities) ---
    CHUNK_TARGET_TOKENS: int = 400
    CHUNK_OVERLAP_TOKENS: int = 60
    CHUNK_MIN_TOKENS: int = 80
    CHUNK_MAX_TOKENS: int = 900
    MIN_CHARS_PER_CHUNK: int = 40
    MIN_CHARS_PER_PAGE: int = 80

    # --- 4.6 Retrieval and Gate ---
    RETRIEVAL_CANDIDATES: int = 50
    RRF_K: int = 60
    RETRIEVAL_TOP_K: int = 12
    CONTEXT_CHUNKS: int = 8
    HNSW_EF_SEARCH: int = Field(default=40, le=200)
    MIN_TOP_SIMILARITY: float = 0.55
    MIN_SUPPORTING_SIMILARITY: float = 0.45
    MIN_SUPPORTING_CHUNKS: int = 2

    # --- 4.7 Ingestion ---
    MAX_UPLOAD_MB: int = 20
    MAX_PAGES: int = 500
    INGESTION_CONCURRENCY: int = 2
    INGESTION_TIMEOUT_SECONDS: int = 600
    PDF_PARSE_TIMEOUT_SECONDS: int = 120
    STORAGE_BUDGET_MB: int = 400

    # --- 4.8 Security ---
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    RATE_LIMIT_QUERIES_PER_HOUR: int = 20
    RATE_LIMIT_QUERIES_PER_MINUTE: int = 5
    RATE_LIMIT_UPLOADS_PER_HOUR: int = 5
    RATE_LIMIT_UPLOADS_PER_DAY: int = 20
    RATE_LIMIT_BYTES_PER_DAY: int = 104857600

    @property
    def allowed_origins_list(self) -> List[str]:
        origins = [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]
        if "http://localhost:3000" in origins and "http://127.0.0.1:3000" not in origins:
            origins.append("http://127.0.0.1:3000")
        if "http://127.0.0.1:3000" in origins and "http://localhost:3000" not in origins:
            origins.append("http://localhost:3000")
        return origins

    @model_validator(mode="after")
    def validate_all_constraints(self) -> "Settings":
        # Force statement_cache_size to 0 on port 6543 (transaction pooler)
        if ":6543" in self.DATABASE_URL:
            self.DB_STATEMENT_CACHE_SIZE = 0

        # Chunking constraints
        if self.CHUNK_OVERLAP_TOKENS >= self.CHUNK_TARGET_TOKENS:
            raise ValueError(
                f"CHUNK_OVERLAP_TOKENS ({self.CHUNK_OVERLAP_TOKENS}) must be < "
                f"CHUNK_TARGET_TOKENS ({self.CHUNK_TARGET_TOKENS})"
            )
        if self.CHUNK_MIN_TOKENS > self.CHUNK_TARGET_TOKENS:
            raise ValueError(
                f"CHUNK_MIN_TOKENS ({self.CHUNK_MIN_TOKENS}) must be <= "
                f"CHUNK_TARGET_TOKENS ({self.CHUNK_TARGET_TOKENS})"
            )
        if self.CHUNK_MAX_TOKENS * 1.2 >= 2048:
            raise ValueError(
                f"CHUNK_MAX_TOKENS ({self.CHUNK_MAX_TOKENS}) * 1.2 must be < 2048"
            )

        # Retrieval and Gate constraints
        if self.RETRIEVAL_TOP_K < self.CONTEXT_CHUNKS:
            raise ValueError(
                f"RETRIEVAL_TOP_K ({self.RETRIEVAL_TOP_K}) must be >= "
                f"CONTEXT_CHUNKS ({self.CONTEXT_CHUNKS})"
            )
        if self.HNSW_EF_SEARCH > 200:
            raise ValueError(
                f"HNSW_EF_SEARCH ({self.HNSW_EF_SEARCH}) must be <= 200"
            )
        if self.MIN_SUPPORTING_SIMILARITY > self.MIN_TOP_SIMILARITY:
            raise ValueError(
                f"MIN_SUPPORTING_SIMILARITY ({self.MIN_SUPPORTING_SIMILARITY}) must be <= "
                f"MIN_TOP_SIMILARITY ({self.MIN_TOP_SIMILARITY})"
            )
        for sim, name in [
            (self.MIN_TOP_SIMILARITY, "MIN_TOP_SIMILARITY"),
            (self.MIN_SUPPORTING_SIMILARITY, "MIN_SUPPORTING_SIMILARITY"),
        ]:
            if not (-1.0 <= sim <= 1.0):
                raise ValueError(f"{name} ({sim}) must be within [-1.0, 1.0]")

        # Production security constraints
        if self.APP_ENV == AppEnv.PRODUCTION:
            if "*" in self.allowed_origins_list:
                raise ValueError("ALLOWED_ORIGINS must not contain wildcard '*' in production")
            if self.LOG_LEVEL == LogLevel.DEBUG:
                raise ValueError("LOG_LEVEL must not be DEBUG in production")

        return self


def get_settings() -> Settings:
    """Load and validate settings. Raises ValidationError if invalid."""
    return Settings()
