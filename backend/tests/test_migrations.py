from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from tests.conftest import TEST_DATABASE_URL, requires_db

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    assert TEST_DATABASE_URL
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return cfg


def _current_revision() -> str | None:
    assert TEST_DATABASE_URL
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as conn:
            exists = conn.execute(text("SELECT to_regclass('alembic_version')")).scalar()
            if not exists:
                return None
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()


AUTH_TABLES = {"users", "auth_sessions", "refresh_tokens", "media_items"}


def _tables() -> set[str]:
    assert TEST_DATABASE_URL
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
            return set(rows)
    finally:
        engine.dispose()


@requires_db
def test_migrations_upgrade_downgrade_upgrade() -> None:
    cfg = _config()
    command.upgrade(cfg, "head")
    assert _current_revision() == "0002_auth"
    assert AUTH_TABLES <= _tables()
    command.downgrade(cfg, "0001_baseline")
    assert _current_revision() == "0001_baseline"
    assert not (AUTH_TABLES & _tables())
    command.downgrade(cfg, "base")
    assert _current_revision() is None
    command.upgrade(cfg, "head")
    assert _current_revision() == "0002_auth"
    assert AUTH_TABLES <= _tables()
