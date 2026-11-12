"""Application settings, read from environment variables (and an optional .env file).

Never hard-code secrets here. Real values belong in each environment's secret store.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "mediavault-api"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"

    # Format: postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME
    database_url: str = "postgresql+psycopg://mediavault:mediavault@localhost:5432/mediavault"
    database_connect_timeout_s: int = 3

    # Comma-separated exact origins allowed to call the API from a browser.
    cors_allow_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
