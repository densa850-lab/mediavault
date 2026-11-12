"""Shared fixtures.

Tests that need a real database read TEST_DATABASE_URL (environment first, then the repo-root
.env file), e.g.
    postgresql+psycopg://mediavault:mediavault@localhost:5432/mediavault_test
They are skipped (and reported as skipped) when it is not set.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or (
    dotenv_values(_ROOT_ENV).get("TEST_DATABASE_URL") if _ROOT_ENV.exists() else None
)
requires_db = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")

# A port nothing listens on: used to prove the API reports a database outage.
UNREACHABLE_DB_URL = "postgresql+psycopg://nobody:nopass@127.0.0.1:1/none"


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "test",
        "database_url": TEST_DATABASE_URL or UNREACHABLE_DB_URL,
        "database_connect_timeout_s": 2,
        "cors_allow_origins": ["http://localhost:3000"],
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as c:
        yield c


@pytest.fixture
def down_client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(database_url=UNREACHABLE_DB_URL))) as c:
        yield c
