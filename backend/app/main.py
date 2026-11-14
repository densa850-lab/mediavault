"""MediaVault API application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.auth.rate_limit import FixedWindowRateLimiter
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log
from app.core.security import SecurityHeadersMiddleware, StrictCORSMiddleware
from app.db.session import create_engine, create_sessionmaker


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, object]]:
    """Validation errors WITHOUT the submitted values (MV-019: never echo a password back)."""
    return [{k: v for k, v in err.items() if k in ("type", "loc", "msg")} for err in exc.errors()]


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(_safe_validation_errors(exc))},
        headers={"Cache-Control": "no-store"},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    is_production = settings.environment == "production"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_engine(settings)
        app.state.sessionmaker = create_sessionmaker(app.state.engine)
        log.info("startup", environment=settings.environment, version=settings.app_version)
        if settings.is_deployed and not settings.auth_trusted_proxies:
            # MV-025: not an error (the API may serve only the Android app directly), but then
            # every website user arrives from the website server's address and shares its bucket.
            log.warning(
                "auth.no_trusted_proxies",
                hint="AUTH_TRUSTED_PROXIES is empty: requests relayed by the website share one "
                "rate-limit bucket. Set it to the website server's address and set "
                "WEB_TRUSTED_PROXY_HOPS on the website.",
            )
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
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.include_router(api_router)
    return app


app = create_app()
