"""FastAPI application factory and middleware wiring.
Governing spec: BE-01, BE-12, BE-13.
"""

import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.core.config import get_settings
from app.core.errors import AppError, ValidationError
from app.core.logging import setup_logging, logger
from app.db.pool import init_pool, close_pool
from app.api.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL.value)
    logger.info(f"Starting Verity Backend v{settings.APP_VERSION} in {settings.APP_ENV.value} mode...")
    
    # Initialize DB pool unless skipped by test flag
    try:
        await init_pool(settings)
    except Exception as e:
        logger.warning(f"Database pool initialization deferred or failed: {e}")

    yield

    await close_pool()
    logger.info("Verity Backend stopped.")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Verity — Document Intelligence API",
        version=settings.APP_VERSION,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    # CORS Middleware (BE-12-R10, BE-12-R11)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Content-Type", "Authorization", "X-Session-Id", "X-Request-Id"],
        expose_headers=["X-Request-Id", "Retry-After"],
    )

    # Request ID Middleware (BE-12-R5)
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    # Global Exception Handlers (BE-12-R6, BE-13)
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        request_id = request.headers.get("X-Request-Id", "")
        headers = {}
        if hasattr(exc, "retry_after"):
            headers["Retry-After"] = str(getattr(exc, "retry_after"))
        
        body = {
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "request_id": request_id,
            }
        }
        return JSONResponse(status_code=exc.status, content=body, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        request_id = request.headers.get("X-Request-Id", "")
        body = {
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Some of the information sent wasn't valid.",
                "details": {"errors": exc.errors()},
                "request_id": request_id,
            }
        }
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled server exception on {request.url.path}: {exc}", exc_info=True)
        request_id = request.headers.get("X-Request-Id", "")
        body = {
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An internal error occurred while processing your request.",
                "details": str(exc),
                "request_id": request_id,
            }
        }
        return JSONResponse(status_code=500, content=body)

    # Mount API v1 routers
    app.include_router(health_router, prefix="/api/v1")
    from app.api.documents import router as documents_router
    from app.api.queries import router as query_router, queries_router
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(query_router, prefix="/api/v1")
    app.include_router(queries_router, prefix="/api/v1")

    return app


app = create_app()
