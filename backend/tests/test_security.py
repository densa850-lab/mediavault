from fastapi.testclient import TestClient


def test_cors_allows_configured_origin(down_client: TestClient) -> None:
    res = down_client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejects_unknown_origin(down_client: TestClient) -> None:
    res = down_client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers


def test_security_headers_present(down_client: TestClient) -> None:
    res = down_client.get("/api/v1/health")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["referrer-policy"] == "no-referrer"


def test_settings_parse_comma_separated_origins(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import Settings

    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000, http://10.0.2.2:3000")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.cors_allow_origins == ["http://localhost:3000", "http://10.0.2.2:3000"]
