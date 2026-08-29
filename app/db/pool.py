"""Database connection pooling and schema verification.
Governing spec: BE-01 §7.1, BE-02-R2.
"""

from typing import Optional
import asyncpg
from app.core.config import Settings
from app.core.errors import DatabaseUnavailableError
from app.core.logging import logger

_pool: Optional[asyncpg.Pool] = None


async def init_pool(settings: Settings) -> asyncpg.Pool:
    """Initialize the global asyncpg connection pool."""
    global _pool
    try:
        _pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=settings.DB_POOL_MIN,
            max_size=settings.DB_POOL_MAX,
            statement_cache_size=settings.DB_STATEMENT_CACHE_SIZE,
            command_timeout=30,
        )
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise DatabaseUnavailableError()

    # BE-02-R2: Verify schema version at startup
    async with _pool.acquire() as conn:
        try:
            version = await conn.fetchval("SELECT MAX(version) FROM schema_version")
        except Exception as e:
            logger.error(f"Failed to query schema_version: {e}")
            raise DatabaseUnavailableError("schema_version table unreadable or missing")

        if version != settings.EXPECTED_SCHEMA_VERSION:
            logger.critical(
                f"Schema version mismatch: expected {settings.EXPECTED_SCHEMA_VERSION}, found {version}"
            )
            raise RuntimeError(
                f"Database schema version mismatch: expected {settings.EXPECTED_SCHEMA_VERSION}, found {version}"
            )

    logger.info(f"Database connection pool initialized (schema version {version}).")
    return _pool


async def close_pool() -> None:
    """Close the global connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed.")


def get_pool() -> asyncpg.Pool:
    """Dependency injector for connection pool."""
    if _pool is None:
        raise DatabaseUnavailableError("Database pool is not initialized.")
    return _pool
