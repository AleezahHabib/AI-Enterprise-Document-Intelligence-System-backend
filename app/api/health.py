"""Health and readiness endpoints.
Governing spec: BE-01-R27, BE-12 §4.
"""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
import asyncpg
from app.db.pool import get_pool
from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str


class ReadinessResponse(BaseModel):
    status: str
    schema_version: int
    database: str


@router.get("/health", response_model=HealthResponse)
async def get_health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Fast liveness probe and wake ping (<50ms, BE-01-R27)."""
    return HealthResponse(status="ok", version=settings.APP_VERSION)


@router.get("/health/ready", response_model=ReadinessResponse)
async def get_readiness(
    response: Response,
    settings: Settings = Depends(get_settings),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ReadinessResponse:
    """Readiness probe verifying database connectivity and schema version."""
    try:
        async with pool.acquire() as conn:
            version = await conn.fetchval("SELECT MAX(version) FROM schema_version")
            if version == settings.EXPECTED_SCHEMA_VERSION:
                return ReadinessResponse(
                    status="ready",
                    schema_version=version,
                    database="ok",
                )
            else:
                response.status_code = 503
                return ReadinessResponse(
                    status="degraded",
                    schema_version=version or 0,
                    database="ok",
                )
    except Exception:
        response.status_code = 503
        return ReadinessResponse(
            status="degraded",
            schema_version=0,
            database="unavailable",
        )
