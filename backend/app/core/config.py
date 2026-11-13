"""Application settings, read from environment variables (and an optional .env file).

Never hard-code secrets here. Real values belong in each environment's secret store.

Deployed environments (staging, production) are strict:
- DATABASE_URL is required. There is no built-in fallback (MV-001).
- CORS origins must be explicit https:// origins. "*" and http:// are rejected (MV-002).
- JWT_SECRET is required and must be at least 32 characters. The dev/test default is refused.
A misconfiguration raises ConfigurationError at startup with a message that never contains
the database URL, credentials or any other configured value.
"""

from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]
DEPLOYED_ENVIRONMENTS: frozenset[str] = frozenset({"staging", "production"})

# Local-only default for development/test (matches infrastructure/docker/compose.dev.yml).
# It is never used in staging or production.
_LOCAL_DEV_DATABASE_URL = "postgresql+psycopg://mediavault:mediavault@localhost:5432/mediavault"
# Publicly known, development/test only. Staging/production refuse it (see validator below).
_DEV_ONLY_JWT_SECRET = "dev-only-insecure-jwt-secret-not-for-deployment"  # noqa: S105
MIN_JWT_SECRET_LENGTH = 32


class ConfigurationError(RuntimeError):
    """Startup configuration is invalid. The message is safe to log: it names settings only."""


def _is_valid_https_origin(origin: str) -> bool:
    if "*" in origin:
        return False
    try:
        parts = urlsplit(origin)
        port = parts.port  # raises ValueError for a malformed port
    except ValueError:
        return False
    del port
    return (
        parts.scheme == "https"
        and bool(parts.hostname)
        and parts.username is None
        and parts.password is None
        and parts.path in ("", "/")
        and not parts.query
        and not parts.fragment
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        # Never echo raw input values (which may include DATABASE_URL) in validation errors.
        hide_input_in_errors=True,
    )

    app_name: str = "mediavault-api"
    app_version: str = "0.1.0"
    environment: Environment = "development"
    log_level: str = "INFO"

    # Format: postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME
    # Required in staging/production. Development/test fall back to the local-only default.
    database_url: str | None = None
    database_connect_timeout_s: int = 3

    # --- Auth (Phase 2 step 1) ---
    # HS256 signing key for access tokens. Required in staging/production (>= 32 chars).
    jwt_secret: str | None = None
    access_token_ttl_s: int = 15 * 60
    refresh_token_ttl_s: int = 30 * 24 * 60 * 60
    # In-memory, per-process fixed-window limits for /auth/login and /auth/register.
    auth_rate_limit_per_ip: int = 20
    auth_rate_limit_per_email: int = 5
    auth_rate_limit_window_s: int = 60
    # Peers (e.g. the website's server) allowed to pass the real client IP in X-Forwarded-For.
    # Comma-separated exact IPs. Empty = never trust X-Forwarded-For.
    auth_trusted_proxies: Annotated[list[str], NoDecode] = []

    # Comma-separated exact origins allowed to call the API from a browser.
    cors_allow_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_allow_origins", "auth_trusted_proxies", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @model_validator(mode="after")
    def _check_deployed_environment(self) -> "Settings":
        # ConfigurationError is not a ValueError, so pydantic re-raises it unchanged (no input
        # values attached).
        if self.environment in DEPLOYED_ENVIRONMENTS:
            if not (self.database_url and self.database_url.strip()):
                raise ConfigurationError(
                    f"DATABASE_URL must be set when ENVIRONMENT={self.environment}; "
                    "there is no default database outside development/test."
                )
            bad = [o for o in self.cors_allow_origins if not _is_valid_https_origin(o)]
            if bad:
                raise ConfigurationError(
                    f"CORS_ALLOW_ORIGINS is invalid for ENVIRONMENT={self.environment}: "
                    f"{len(bad)} origin(s) are not explicit https:// origins "
                    "('*', wildcards, http://, paths and credentials are rejected)."
                )
            secret = (self.jwt_secret or "").strip()
            if not secret or secret == _DEV_ONLY_JWT_SECRET:
                raise ConfigurationError(
                    f"JWT_SECRET must be set when ENVIRONMENT={self.environment}; "
                    "the development default is not accepted."
                )
            if len(secret) < MIN_JWT_SECRET_LENGTH:
                raise ConfigurationError(
                    f"JWT_SECRET is too short for ENVIRONMENT={self.environment}: "
                    f"at least {MIN_JWT_SECRET_LENGTH} characters are required."
                )
        else:
            if not self.database_url:
                self.database_url = _LOCAL_DEV_DATABASE_URL
            if not self.jwt_secret:
                self.jwt_secret = _DEV_ONLY_JWT_SECRET
        return self

    @property
    def is_deployed(self) -> bool:
        return self.environment in DEPLOYED_ENVIRONMENTS

    @property
    def resolved_jwt_secret(self) -> str:
        assert self.jwt_secret is not None
        return self.jwt_secret

    @property
    def resolved_database_url(self) -> str:
        """The database URL to connect to (always set once validation has passed)."""
        assert self.database_url is not None
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
