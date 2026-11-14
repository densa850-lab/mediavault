"""Shared fixtures.

Tests that need a real database read TEST_DATABASE_URL (environment first, then the repo-root
.env file), e.g.
    postgresql+psycopg://mediavault:mediavault@localhost:5432/mediavault_test
They are skipped (and reported as skipped) when it is not set.
"""

import os

# The app refuses to start without an explicit ENVIRONMENT (MV-018). Tests run as "test" unless
# the caller set something else. Must happen before app.main is imported (it builds an app).
os.environ.setdefault("ENVIRONMENT", "test")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from dotenv import dotenv_values  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

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
        # Generous auth limits so only the dedicated rate-limit tests hit them.
        "auth_rate_limit_per_ip": 1000,
        "auth_rate_limit_per_email": 1000,
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


BACKEND_DIR = Path(__file__).resolve().parents[1]


def migrate_test_db_to_head() -> None:
    from alembic import command
    from alembic.config import Config

    assert TEST_DATABASE_URL
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(cfg, "head")


def truncate_auth_tables() -> None:
    from sqlalchemy import create_engine, text

    assert TEST_DATABASE_URL
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE users, auth_sessions, refresh_tokens, media_items CASCADE"))
    finally:
        engine.dispose()


@pytest.fixture
def db_client() -> Iterator[TestClient]:
    """A client on a migrated, empty test database (requires TEST_DATABASE_URL)."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    migrate_test_db_to_head()
    truncate_auth_tables()
    with TestClient(create_app(make_settings())) as c:
        yield c
