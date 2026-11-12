from datetime import datetime

from fastapi.testclient import TestClient

from tests.conftest import requires_db


@requires_db
def test_health_ok_with_real_postgres(client: TestClient) -> None:
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok"}
    assert body["service"] == "mediavault-api"
    assert body["environment"] == "test"
    datetime.fromisoformat(body["time"])


def test_health_reports_database_down(down_client: TestClient) -> None:
    res = down_client.get("/api/v1/health")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "degraded"
    assert body["checks"] == {"database": "error"}
    # No connection details or stack traces leak to clients.
    text = res.text.lower()
    assert "nobody" not in text and "traceback" not in text and "127.0.0.1" not in text


def test_openapi_lists_health(down_client: TestClient) -> None:
    paths = down_client.get("/openapi.json").json()["paths"]
    assert "/api/v1/health" in paths
