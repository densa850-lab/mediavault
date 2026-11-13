"""MediaVault API application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.auth.rate_limit import FixedWindowRateLimiter
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log
from app.core.security import SecurityHeadersMiddleware, StrictCORSMiddleware
from app.db.session import create_engine, create_sessionmaker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    is_production = settings.environment == "production"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_engine(settings)
        app.state.sessionmaker = create_sessionmaker(app.state.engine)
        log.info("startup", environment=settings.environment, version=settings.app_version)
        try:
            yield
        finally:
            await app.state.engine.dispose()

    app = FastAPI(
        title="MediaVault API",
        version=settings.app_version,
        lifespan=lifespan,
        # API docs and the OpenAPI schema are not served in production (MV-004).
        docs_url=None if is_production else "/docs",
        redoc_url=None,
        openapi_url=None if is_production else "/openapi.json",
    )
    app.state.settings = settings
    # Injectable clock: tests move time forward to prove token expiry.
    app.state.clock = lambda: datetime.now(UTC)
    app.state.auth_rate_limiter = FixedWindowRateLimiter(lambda: app.state.clock().timestamp())

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        StrictCORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
    app.include_router(api_router)
    return app


app = create_app()
