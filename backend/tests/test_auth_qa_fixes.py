"""Fixes from Tester's QA of PR #2 (MV-016, MV-019, MV-020, MV-021) on real PostgreSQL."""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings
from tests.test_auth import PASSWORD, A, login, register, sql


@contextmanager
def _client(peer: str = "203.0.113.50", **settings: object) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(**settings)), client=(peer, 40000)) as c:
        yield c


def _bad_login(c: TestClient, i: int, headers: dict[str, str]) -> int:
    body = {"email": f"nobody{i}@example.com", "password": "wrong-password1"}
    return c.post("/api/v1/auth/login", json=body, headers=headers).status_code


# ---------- MV-016: rotating X-Forwarded-For must not bypass the per-IP limit ----------


def test_rotating_x_forwarded_for_from_untrusted_peer_is_limited(db_client: TestClient) -> None:
    with _client(auth_rate_limit_per_ip=5) as c:
        codes = [_bad_login(c, i, {"X-Forwarded-For": f"198.51.100.{i}"}) for i in range(12)]
    assert codes[:5] == [401] * 5
    assert codes[5:] == [429] * 7, codes


def test_rotating_client_ip_header_from_untrusted_peer_is_limited(db_client: TestClient) -> None:
    with _client(auth_rate_limit_per_ip=5, auth_trusted_proxies=["10.0.0.0/8"]) as c:
        codes = [_bad_login(c, i, {"X-MediaVault-Client-IP": f"198.51.100.{i}"}) for i in range(8)]
    assert codes == [401] * 5 + [429] * 3, codes


def test_trusted_proxy_client_ip_header_gives_each_client_its_own_bucket(
    db_client: TestClient,
) -> None:
    with _client("127.0.0.1", auth_rate_limit_per_ip=2, auth_trusted_proxies=["127.0.0.1"]) as c:
        one = {"X-MediaVault-Client-IP": "198.51.100.1", "X-Forwarded-For": "9.9.9.9"}
        two = {"X-MediaVault-Client-IP": "198.51.100.2"}
        assert [_bad_login(c, i, one) for i in range(3)] == [401, 401, 429]
        # A different real client behind the same website server is unaffected...
        assert _bad_login(c, 10, two) == 401
        # ...and changing only X-Forwarded-For does not escape the first client's bucket.
        one_rotated = dict(one, **{"X-Forwarded-For": "8.8.8.8"})
        assert _bad_login(c, 11, one_rotated) == 429


# ---------- MV-019: validation errors never echo submitted values ----------


def test_validation_error_does_not_echo_password(db_client: TestClient) -> None:
    secret = "Sup3rSecret-but-short"  # noqa: S105 - test value
    weak = "abc"
    for path, body in [
        ("/api/v1/auth/register", {"email": A, "password": weak}),
        ("/api/v1/auth/register", {"email": "not-an-email", "password": secret}),
        ("/api/v1/auth/login", {"email": A, "password": secret * 20}),
        ("/api/v1/auth/login", {"email": A}),
    ]:
        res = db_client.post(path, json=body)
        assert res.status_code == 422, (path, res.text)
        text = res.text
        assert secret not in text and '"input"' not in text and '"ctx"' not in text, text
        assert '"abc"' not in text
        errors = res.json()["detail"]
        assert errors and all(set(e) <= {"type", "loc", "msg"} for e in errors)
        assert all("msg" in e and "loc" in e for e in errors)


# ---------- MV-020: token responses are never cached ----------


def test_token_responses_are_no_store(db_client: TestClient) -> None:
    register(db_client, A)
    res = db_client.post("/api/v1/auth/login", json={"email": A, "password": PASSWORD})
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["pragma"] == "no-cache"
    ref = db_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": res.json()["refresh_token"]}
    )
    assert ref.status_code == 200
    assert ref.headers["cache-control"] == "no-store"
    assert ref.headers["pragma"] == "no-cache"
    me = db_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {ref.json()['access_token']}"}
    )
    assert me.headers["cache-control"] == "no-store"


# ---------- MV-021: refresh and logout are rate limited (failures only) ----------


def test_failed_refreshes_are_rate_limited_per_ip(db_client: TestClient) -> None:
    with _client(auth_rate_limit_refresh_failures_per_ip=3) as c:
        codes = [
            c.post("/api/v1/auth/refresh", json={"refresh_token": f"garbage-{i}"}).status_code
            for i in range(6)
        ]
        assert codes == [401, 401, 401, 429, 429, 429], codes
        blocked = c.post("/api/v1/auth/refresh", json={"refresh_token": "garbage-x"})
        assert int(blocked.headers["retry-after"]) >= 1
    # Another IP is unaffected.
    with _client("203.0.113.51", auth_rate_limit_refresh_failures_per_ip=3) as c2:
        res = c2.post("/api/v1/auth/refresh", json={"refresh_token": "garbage"})
        assert res.status_code == 401


def test_successful_refreshes_do_not_count_towards_the_limit(db_client: TestClient) -> None:
    register(db_client, A)
    with _client(auth_rate_limit_refresh_failures_per_ip=2) as c:
        tokens = login(c, A)
        for _ in range(10):
            res = c.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
            assert res.status_code == 200, res.text
            tokens = res.json()


def test_unmatched_logouts_are_rate_limited_per_ip(db_client: TestClient) -> None:
    register(db_client, A)
    with _client(auth_rate_limit_refresh_failures_per_ip=3) as c:
        codes = [
            c.post("/api/v1/auth/logout", json={"refresh_token": f"garbage-{i}"}).status_code
            for i in range(5)
        ]
        assert codes == [204, 204, 204, 429, 429], codes
    # A real logout from another client still works and revokes the session.
    with _client("203.0.113.52", auth_rate_limit_refresh_failures_per_ip=3) as c2:
        tokens = login(c2, A)
        res = c2.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
        assert res.status_code == 204
    assert sql("SELECT revoked_reason FROM auth_sessions")[0][0] == "logout"
