"""Auth API integration tests on real PostgreSQL (skipped without TEST_DATABASE_URL)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from tests.conftest import TEST_DATABASE_URL, make_settings

PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - test value
A = "alice@example.com"
B = "bob@example.com"


def register(c: TestClient, email: str, password: str = PASSWORD) -> None:
    res = c.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert res.status_code == 202, res.text


def login(c: TestClient, email: str, password: str = PASSWORD) -> dict:
    res = c.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()


def auth(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def sql(query: str, **params: object) -> list:
    assert TEST_DATABASE_URL
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.begin() as conn:
            result = conn.execute(text(query), params)
            return list(result) if result.returns_rows else []
    finally:
        engine.dispose()


# ---------- register / login / me ----------


def test_register_login_me(db_client: TestClient) -> None:
    register(db_client, A)
    tokens = login(db_client, A)
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 900
    me = db_client.get("/api/v1/auth/me", headers=auth(tokens))
    assert me.status_code == 200
    assert me.json()["email"] == A
    assert me.json()["is_active"] is True


def test_password_stored_as_argon2id_and_refresh_token_hashed(db_client: TestClient) -> None:
    register(db_client, A)
    tokens = login(db_client, A)
    (row,) = sql("SELECT password_hash FROM users")
    assert row[0].startswith("$argon2id$") and PASSWORD not in row[0]
    hashes = [r[0] for r in sql("SELECT token_hash FROM refresh_tokens")]
    assert len(hashes) == 1 and tokens["refresh_token"] not in hashes
    assert len(hashes[0]) == 64


def test_email_is_case_insensitive_and_unique(db_client: TestClient) -> None:
    register(db_client, "Alice@Example.COM")
    register(db_client, "alice@example.com")  # same response, no second account
    assert sql("SELECT count(*) FROM users")[0][0] == 1
    login(db_client, "ALICE@example.com")


def test_register_existing_email_gives_identical_response(db_client: TestClient) -> None:
    first = db_client.post("/api/v1/auth/register", json={"email": A, "password": PASSWORD})
    again = db_client.post(
        "/api/v1/auth/register", json={"email": A, "password": "another-long-password"}
    )
    assert first.status_code == again.status_code == 202
    assert first.json() == again.json()
    # The original password still works; the second attempt did not overwrite it.
    login(db_client, A)


@pytest.mark.parametrize(
    "body",
    [
        {"email": A, "password": "short"},
        {"email": A, "password": " " * 20},
        {"email": A, "password": "x" * 129},
        {"email": "not-an-email", "password": PASSWORD},
    ],
)
def test_register_validation(db_client: TestClient, body: dict) -> None:
    res = db_client.post("/api/v1/auth/register", json=body)
    assert res.status_code == 422
    assert sql("SELECT count(*) FROM users")[0][0] == 0


def test_login_errors_are_generic(db_client: TestClient) -> None:
    register(db_client, A)
    wrong_pw = db_client.post(
        "/api/v1/auth/login", json={"email": A, "password": "wrong-password1"}
    )
    no_user = db_client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json() == {"detail": "Invalid email or password."}


def test_inactive_user_cannot_login_or_use_tokens(db_client: TestClient) -> None:
    register(db_client, A)
    tokens = login(db_client, A)
    sql("UPDATE users SET is_active = false")
    assert db_client.get("/api/v1/auth/me", headers=auth(tokens)).status_code == 401
    res = db_client.post("/api/v1/auth/login", json={"email": A, "password": PASSWORD})
    assert res.status_code == 401
    assert res.json() == {"detail": "Invalid email or password."}
    ref = db_client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert ref.status_code == 401


@pytest.mark.parametrize(
    "header",
    [None, "Bearer", "Bearer not-a-token", "Basic dXNlcjpwYXNz", "Bearer a.b.c"],
)
def test_me_requires_valid_bearer(db_client: TestClient, header: str | None) -> None:
    headers = {"Authorization": header} if header else {}
    res = db_client.get("/api/v1/auth/me", headers=headers)
    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated."}


# ---------- expiry ----------


def test_access_token_expires(db_client: TestClient) -> None:
    register(db_client, A)
    t0 = datetime.now(UTC)
    db_client.app.state.clock = lambda: t0  # type: ignore[attr-defined]
    tokens = login(db_client, A)
    db_client.app.state.clock = lambda: t0 + timedelta(seconds=899)  # type: ignore[attr-defined]
    assert db_client.get("/api/v1/auth/me", headers=auth(tokens)).status_code == 200
    db_client.app.state.clock = lambda: t0 + timedelta(seconds=900)  # type: ignore[attr-defined]
    assert db_client.get("/api/v1/auth/me", headers=auth(tokens)).status_code == 401


def test_refresh_token_expires(db_client: TestClient) -> None:
    register(db_client, A)
    t0 = datetime.now(UTC)
    db_client.app.state.clock = lambda: t0  # type: ignore[attr-defined]
    tokens = login(db_client, A)
    later = t0 + timedelta(days=30, seconds=1)
    db_client.app.state.clock = lambda: later  # type: ignore[attr-defined]
    res = db_client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert res.status_code == 401
    assert res.json() == {"detail": "Session expired. Sign in again."}


# ---------- refresh rotation and reuse detection ----------


def test_refresh_rotates_tokens(db_client: TestClient) -> None:
    register(db_client, A)
    t1 = login(db_client, A)
    res = db_client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert res.status_code == 200
    t2 = res.json()
    assert t2["refresh_token"] != t1["refresh_token"]
    assert t2["access_token"] != t1["access_token"]
    assert db_client.get("/api/v1/auth/me", headers=auth(t2)).status_code == 200
    # A rotated token chain keeps working.
    t3 = db_client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert t3.status_code == 200


def test_refresh_reuse_revokes_whole_session(db_client: TestClient) -> None:
    register(db_client, A)
    t1 = login(db_client, A)
    t2 = db_client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]}).json()
    # Attacker replays the old (already used) refresh token.
    replay = db_client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert replay.status_code == 401
    # Every token of that session is now dead, including the legitimate new ones.
    assert db_client.get("/api/v1/auth/me", headers=auth(t2)).status_code == 401
    newer = db_client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert newer.status_code == 401
    assert sql("SELECT revoked_reason FROM auth_sessions")[0][0] == "refresh_reuse"


def test_reuse_in_one_session_does_not_affect_other_sessions(db_client: TestClient) -> None:
    register(db_client, A)
    phone = login(db_client, A)
    laptop = login(db_client, A)
    db_client.post("/api/v1/auth/refresh", json={"refresh_token": phone["refresh_token"]})
    db_client.post("/api/v1/auth/refresh", json={"refresh_token": phone["refresh_token"]})
    assert db_client.get("/api/v1/auth/me", headers=auth(laptop)).status_code == 200


def test_unknown_refresh_token_rejected(db_client: TestClient) -> None:
    res = db_client.post("/api/v1/auth/refresh", json={"refresh_token": "made-up-token"})
    assert res.status_code == 401


# ---------- logout / revocation ----------


def test_logout_revokes_access_and_refresh_immediately(db_client: TestClient) -> None:
    register(db_client, A)
    tokens = login(db_client, A)
    res = db_client.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=auth(tokens)
    )
    assert res.status_code == 204
    # The access token is still unexpired but its session is revoked.
    assert db_client.get("/api/v1/auth/me", headers=auth(tokens)).status_code == 401
    ref = db_client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert ref.status_code == 401
    assert sql("SELECT revoked_reason FROM auth_sessions")[0][0] == "logout"


def test_logout_with_only_refresh_token(db_client: TestClient) -> None:
    register(db_client, A)
    tokens = login(db_client, A)
    res = db_client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert res.status_code == 204
    assert db_client.get("/api/v1/auth/me", headers=auth(tokens)).status_code == 401


def test_logout_only_ends_that_session(db_client: TestClient) -> None:
    register(db_client, A)
    one = login(db_client, A)
    two = login(db_client, A)
    db_client.post("/api/v1/auth/logout", headers=auth(one))
    assert db_client.get("/api/v1/auth/me", headers=auth(one)).status_code == 401
    assert db_client.get("/api/v1/auth/me", headers=auth(two)).status_code == 200


def test_logout_with_garbage_is_still_204(db_client: TestClient) -> None:
    res = db_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": "nope"},
        headers={"Authorization": "Bearer nope"},
    )
    assert res.status_code == 204


# ---------- rate limiting ----------


def _limited_client(**limits: int) -> TestClient:
    from app.main import create_app

    return TestClient(create_app(make_settings(**limits)))


def test_login_rate_limited_per_email(db_client: TestClient) -> None:
    register(db_client, A)
    with _limited_client(auth_rate_limit_per_email=3, auth_rate_limit_per_ip=100) as c:
        codes = [
            c.post(
                "/api/v1/auth/login", json={"email": A, "password": "wrong-password1"}
            ).status_code
            for _ in range(3)
        ]
        assert codes == [401, 401, 401]
        blocked = c.post("/api/v1/auth/login", json={"email": A, "password": PASSWORD})
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) >= 1
        assert blocked.json() == {"detail": "Too many attempts. Try again later."}
        # Same IP, different email still allowed (per-email bucket).
        other = c.post("/api/v1/auth/login", json={"email": B, "password": PASSWORD})
        assert other.status_code == 401


def test_login_rate_limit_resets_after_window(db_client: TestClient) -> None:
    register(db_client, A)
    with _limited_client(auth_rate_limit_per_email=2, auth_rate_limit_per_ip=100) as c:
        t0 = datetime.now(UTC)
        c.app.state.clock = lambda: t0  # type: ignore[attr-defined]
        for _ in range(2):
            c.post("/api/v1/auth/login", json={"email": A, "password": "wrong-password1"})
        assert (
            c.post("/api/v1/auth/login", json={"email": A, "password": PASSWORD}).status_code == 429
        )
        c.app.state.clock = lambda: t0 + timedelta(seconds=61)  # type: ignore[attr-defined]
        assert (
            c.post("/api/v1/auth/login", json={"email": A, "password": PASSWORD}).status_code == 200
        )


def test_register_rate_limited_per_ip(db_client: TestClient) -> None:
    with _limited_client(auth_rate_limit_per_ip=2, auth_rate_limit_per_email=100) as c:
        for i in range(2):
            res = c.post(
                "/api/v1/auth/register", json={"email": f"u{i}@example.com", "password": PASSWORD}
            )
            assert res.status_code == 202
        res = c.post(
            "/api/v1/auth/register", json={"email": "u9@example.com", "password": PASSWORD}
        )
        assert res.status_code == 429
    assert sql("SELECT count(*) FROM users")[0][0] == 2
