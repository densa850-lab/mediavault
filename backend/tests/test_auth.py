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


def _set_clock(c: TestClient, when: datetime) -> None:
    c.app.state.clock = lambda: when  # type: ignore[attr-defined]


def _refresh(c: TestClient, raw: str):  # noqa: ANN202 - test helper
    return c.post("/api/v1/auth/refresh", json={"refresh_token": raw})


GRACE = make_settings().refresh_reuse_grace_s


def test_refresh_reuse_after_grace_revokes_whole_session(db_client: TestClient) -> None:
    register(db_client, A)
    t0 = datetime.now(UTC)
    _set_clock(db_client, t0)
    t1 = login(db_client, A)
    t2 = _refresh(db_client, t1["refresh_token"]).json()
    # Attacker replays the old (already used) refresh token after the concurrency grace.
    _set_clock(db_client, t0 + timedelta(seconds=GRACE + 1))
    replay = _refresh(db_client, t1["refresh_token"])
    assert replay.status_code == 401
    # Every token of that session is now dead, including the legitimate new ones.
    assert db_client.get("/api/v1/auth/me", headers=auth(t2)).status_code == 401
    assert _refresh(db_client, t2["refresh_token"]).status_code == 401
    assert sql("SELECT revoked_reason FROM auth_sessions")[0][0] == "refresh_reuse"


def test_reuse_within_grace_returns_same_successor(db_client: TestClient) -> None:
    register(db_client, A)
    t0 = datetime.now(UTC)
    _set_clock(db_client, t0)
    t1 = login(db_client, A)
    first = _refresh(db_client, t1["refresh_token"]).json()
    _set_clock(db_client, t0 + timedelta(seconds=GRACE))  # last second of the grace window
    second = _refresh(db_client, t1["refresh_token"])
    assert second.status_code == 200
    second = second.json()
    assert second["refresh_token"] == first["refresh_token"]  # same successor, not a new branch
    assert db_client.get("/api/v1/auth/me", headers=auth(first)).status_code == 200
    assert db_client.get("/api/v1/auth/me", headers=auth(second)).status_code == 200
    assert sql("SELECT revoked_at FROM auth_sessions")[0][0] is None
    # Only one successor row exists for the session (login token + one successor).
    assert sql("SELECT count(*) FROM refresh_tokens")[0][0] == 2
    # The shared successor keeps rotating normally.
    assert _refresh(db_client, first["refresh_token"]).status_code == 200


def test_reuse_within_grace_after_successor_used_revokes(db_client: TestClient) -> None:
    """Grace only covers the direct, still-unused successor: an older branch is a replay."""
    register(db_client, A)
    t0 = datetime.now(UTC)
    _set_clock(db_client, t0)
    t1 = login(db_client, A)
    t2 = _refresh(db_client, t1["refresh_token"]).json()
    t3 = _refresh(db_client, t2["refresh_token"]).json()
    assert _refresh(db_client, t1["refresh_token"]).status_code == 401
    assert db_client.get("/api/v1/auth/me", headers=auth(t3)).status_code == 401
    assert sql("SELECT revoked_reason FROM auth_sessions")[0][0] == "refresh_reuse"


def test_grace_disabled_means_strict_single_use(db_client: TestClient) -> None:
    from app.main import create_app

    with TestClient(create_app(make_settings(refresh_reuse_grace_s=0))) as c:
        register(c, A)
        t1 = login(c, A)
        t2 = _refresh(c, t1["refresh_token"]).json()
        assert _refresh(c, t1["refresh_token"]).status_code == 401
        assert c.get("/api/v1/auth/me", headers=auth(t2)).status_code == 401


def test_grace_nonce_cleared_once_successor_used_and_no_raw_tokens_stored(
    db_client: TestClient,
) -> None:
    register(db_client, A)
    t1 = login(db_client, A)
    t2 = _refresh(db_client, t1["refresh_token"]).json()
    rows = sql("SELECT token_hash, successor_nonce, replaced_by_id FROM refresh_tokens")
    hashes = {r[0] for r in rows}
    for raw in (t1["refresh_token"], t2["refresh_token"]):
        assert raw not in hashes  # only sha256 digests are stored
        assert all(raw.encode() not in bytes(r[1] or b"") for r in rows)
    assert sum(1 for r in rows if r[1] is not None) == 1  # t1 holds the nonce for t2
    _refresh(db_client, t2["refresh_token"])
    rows = sql("SELECT successor_nonce FROM refresh_tokens WHERE replaced_by_id IS NOT NULL")
    assert sum(1 for r in rows if r[0] is not None) == 1  # only the newest predecessor keeps one


def test_grace_reissue_on_revoked_or_expired_session_fails(db_client: TestClient) -> None:
    register(db_client, A)
    t1 = login(db_client, A)
    t2 = _refresh(db_client, t1["refresh_token"]).json()
    db_client.post("/api/v1/auth/logout", headers=auth(t2))
    assert _refresh(db_client, t1["refresh_token"]).status_code == 401


def test_reuse_in_one_session_does_not_affect_other_sessions(db_client: TestClient) -> None:
    register(db_client, A)
    t0 = datetime.now(UTC)
    _set_clock(db_client, t0)
    phone = login(db_client, A)
    laptop = login(db_client, A)
    _refresh(db_client, phone["refresh_token"])
    _set_clock(db_client, t0 + timedelta(seconds=GRACE + 1))
    assert _refresh(db_client, phone["refresh_token"]).status_code == 401
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
