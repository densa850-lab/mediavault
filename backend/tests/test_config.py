"""Configuration hardening for deployed environments (MV-001, MV-002, MV-004)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import ConfigurationError, Settings
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]
SECRET_URL = "postgresql+psycopg://fake_user:FAKE-test-only-pw@db.internal.example:5432/mv"  # noqa: S105 - fake test value
TRUSTED = "https://app.mediavault.example"
PROD_JWT = "fake-test-only-jwt-signing-key-0123456789abcdef"  # noqa: S105 - fake test value
UNREACHABLE_DB_URL = "postgresql+psycopg://nobody:nopass@127.0.0.1:1/none"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ENVIRONMENT", "DATABASE_URL", "CORS_ALLOW_ORIGINS", "JWT_SECRET"):
        monkeypatch.delenv(name, raising=False)


def _settings(**kw: object) -> Settings:
    # Deployed environments now also need JWT_SECRET (Phase 2 step 1); supply a valid one unless a
    # test sets it explicitly. The MV-001/MV-002 checks run before the JWT check.
    kw.setdefault("jwt_secret", PROD_JWT)
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


# ---------- MV-001: DATABASE_URL required in staging/production ----------


@pytest.mark.parametrize("env", ["staging", "production"])
def test_deployed_env_without_database_url_fails_fast(env: str) -> None:
    with pytest.raises(ConfigurationError) as exc:
        _settings(environment=env, cors_allow_origins=[TRUSTED])
    msg = str(exc.value)
    assert "DATABASE_URL must be set" in msg
    assert "mediavault:mediavault" not in msg and "postgresql" not in msg


@pytest.mark.parametrize("env", ["staging", "production"])
def test_deployed_env_blank_database_url_fails_fast(env: str) -> None:
    with pytest.raises(ConfigurationError):
        _settings(environment=env, database_url="   ", cors_allow_origins=[TRUSTED])


@pytest.mark.parametrize("env", ["staging", "production"])
def test_deployed_env_database_url_from_environment_variable(
    env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENVIRONMENT", env)
    monkeypatch.setenv("DATABASE_URL", SECRET_URL)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", TRUSTED)
    s = _settings()
    assert s.resolved_database_url == SECRET_URL


@pytest.mark.parametrize("env", ["development", "test"])
def test_dev_and_test_keep_local_default(env: str) -> None:
    s = _settings(environment=env)
    assert s.resolved_database_url.startswith("postgresql+psycopg://")
    assert "localhost" in s.resolved_database_url


def test_error_never_prints_credentials_when_other_settings_are_invalid() -> None:
    # A real secret URL is set, but CORS is invalid: the error must not echo the URL.
    with pytest.raises(ConfigurationError) as exc:
        _settings(environment="production", database_url=SECRET_URL, cors_allow_origins=["*"])
    msg = str(exc.value)
    assert "FAKE-test-only-pw" not in msg and "fake_user" not in msg and "db.internal" not in msg


def test_pydantic_validation_errors_hide_input_values() -> None:
    with pytest.raises(Exception) as exc:  # noqa: B017 - pydantic ValidationError
        _settings(environment="production", database_url=SECRET_URL, log_level=["not-a-str"])
    assert "FAKE-test-only-pw" not in str(exc.value)


def test_production_import_without_database_url_exits_with_safe_error(tmp_path: Path) -> None:
    """Starting the real app module in production with no DATABASE_URL must fail at startup."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"DATABASE_URL", "TEST_DATABASE_URL", "CORS_ALLOW_ORIGINS", "JWT_SECRET"}
    }
    env.update(
        ENVIRONMENT="production",
        CORS_ALLOW_ORIGINS=TRUSTED,
        PYTHONPATH=str(BACKEND_DIR),
    )
    # cwd=tmp_path so no .env file can supply a DATABASE_URL.
    proc = subprocess.run(  # noqa: S603 - fixed argv, test only
        [sys.executable, "-c", "import app.main"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    assert "ConfigurationError" in proc.stderr
    assert "DATABASE_URL must be set" in proc.stderr
    assert "mediavault:mediavault" not in proc.stderr


# ---------- MV-002: strict CORS in staging/production ----------

BAD_ORIGINS = [
    ["*"],
    ["https://*.mediavault.example"],
    ["http://app.mediavault.example"],
    ["http://localhost:3000"],
    [TRUSTED, "http://app.mediavault.example"],
    ["https://user:pw@app.mediavault.example"],
    ["https://app.mediavault.example/path"],
    ["https://app.mediavault.example?x=1"],
    ["https://"],
    ["app.mediavault.example"],
    ["https://app.mediavault.example:notaport"],
]


@pytest.mark.parametrize("env", ["staging", "production"])
@pytest.mark.parametrize("origins", BAD_ORIGINS)
def test_deployed_env_rejects_unsafe_cors_origins(env: str, origins: list[str]) -> None:
    with pytest.raises(ConfigurationError) as exc:
        _settings(environment=env, database_url=SECRET_URL, cors_allow_origins=origins)
    assert "CORS_ALLOW_ORIGINS is invalid" in str(exc.value)
    assert "FAKE-test-only-pw" not in str(exc.value)


def test_deployed_env_rejects_wildcard_from_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", SECRET_URL)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    with pytest.raises(ConfigurationError):
        _settings()


@pytest.mark.parametrize("env", ["staging", "production"])
def test_deployed_env_accepts_https_origins(env: str) -> None:
    s = _settings(
        environment=env,
        database_url=SECRET_URL,
        cors_allow_origins=[TRUSTED, "https://admin.mediavault.example:8443"],
    )
    assert s.cors_allow_origins == [TRUSTED, "https://admin.mediavault.example:8443"]


def test_development_still_allows_local_http_origin() -> None:
    s = _settings(environment="development", cors_allow_origins=["http://localhost:3000"])
    assert s.cors_allow_origins == ["http://localhost:3000"]


def _prod_client() -> TestClient:
    settings = _settings(
        environment="production",
        database_url=UNREACHABLE_DB_URL,
        database_connect_timeout_s=1,
        cors_allow_origins=[TRUSTED],
    )
    return TestClient(create_app(settings))


def test_production_trusted_https_origin_gets_cors_headers() -> None:
    with _prod_client() as c:
        pre = c.options(
            "/api/v1/health",
            headers={"Origin": TRUSTED, "Access-Control-Request-Method": "GET"},
        )
        assert pre.status_code == 200
        assert pre.headers["access-control-allow-origin"] == TRUSTED
        assert pre.headers["access-control-allow-credentials"] == "true"
        res = c.get("/api/v1/health", headers={"Origin": TRUSTED})
        assert res.headers["access-control-allow-origin"] == TRUSTED


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "http://app.mediavault.example", "null"]
)
def test_production_untrusted_origin_gets_no_cors_headers(origin: str) -> None:
    with _prod_client() as c:
        res = c.get("/api/v1/health", headers={"Origin": origin})
        assert "access-control-allow-origin" not in res.headers
        assert "access-control-allow-credentials" not in res.headers
        pre = c.options(
            "/api/v1/health",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
        assert pre.status_code == 400
        assert "access-control-allow-origin" not in pre.headers


# ---------- MV-004: no OpenAPI schema in production ----------


def test_production_does_not_serve_openapi_or_docs() -> None:
    with _prod_client() as c:
        assert c.get("/openapi.json").status_code == 404
        assert c.get("/docs").status_code == 404
        assert c.get("/redoc").status_code == 404


def test_staging_still_serves_openapi() -> None:
    s = _settings(
        environment="staging",
        database_url=UNREACHABLE_DB_URL,
        database_connect_timeout_s=1,
        cors_allow_origins=[TRUSTED],
    )
    with TestClient(create_app(s)) as c:
        assert c.get("/openapi.json").status_code == 200


# ---------- Phase 2 step 1: JWT_SECRET required in staging/production ----------


@pytest.mark.parametrize("env", ["staging", "production"])
def test_deployed_env_without_jwt_secret_fails_fast(env: str) -> None:
    with pytest.raises(ConfigurationError) as exc:
        _settings(
            environment=env, database_url=SECRET_URL, cors_allow_origins=[TRUSTED], jwt_secret=None
        )
    msg = str(exc.value)
    assert "JWT_SECRET must be set" in msg
    assert "FAKE-test-only-pw" not in msg


@pytest.mark.parametrize("env", ["staging", "production"])
def test_deployed_env_rejects_dev_default_jwt_secret(env: str) -> None:
    from app.core.config import _DEV_ONLY_JWT_SECRET

    with pytest.raises(ConfigurationError):
        _settings(
            environment=env,
            database_url=SECRET_URL,
            cors_allow_origins=[TRUSTED],
            jwt_secret=_DEV_ONLY_JWT_SECRET,
        )


@pytest.mark.parametrize("env", ["staging", "production"])
def test_deployed_env_rejects_short_jwt_secret(env: str) -> None:
    with pytest.raises(ConfigurationError) as exc:
        _settings(
            environment=env,
            database_url=SECRET_URL,
            cors_allow_origins=[TRUSTED],
            jwt_secret="short-but-not-empty",
        )
    assert "too short" in str(exc.value)
    assert "short-but-not-empty" not in str(exc.value)


def test_deployed_env_jwt_secret_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", SECRET_URL)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", TRUSTED)
    monkeypatch.setenv("JWT_SECRET", PROD_JWT)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.resolved_jwt_secret == PROD_JWT


@pytest.mark.parametrize("env", ["development", "test"])
def test_dev_and_test_get_a_dev_jwt_secret(env: str) -> None:
    s = Settings(_env_file=None, environment=env)  # type: ignore[call-arg]
    assert len(s.resolved_jwt_secret) >= 32


def test_production_import_without_jwt_secret_exits_with_safe_error(tmp_path: Path) -> None:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"DATABASE_URL", "TEST_DATABASE_URL", "CORS_ALLOW_ORIGINS", "JWT_SECRET"}
    }
    env.update(
        ENVIRONMENT="production",
        DATABASE_URL=SECRET_URL,
        CORS_ALLOW_ORIGINS=TRUSTED,
        PYTHONPATH=str(BACKEND_DIR),
    )
    proc = subprocess.run(  # noqa: S603 - fixed argv, test only
        [sys.executable, "-c", "import app.main"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    assert "JWT_SECRET must be set" in proc.stderr
    assert "FAKE-test-only-pw" not in proc.stderr
