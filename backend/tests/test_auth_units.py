"""Unit tests for password hashing, tokens and the rate limiter (no database)."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth.passwords import (
    MIN_PASSWORD_LENGTH,
    hash_password,
    password_policy_problem,
    verify_password,
)
from app.auth.rate_limit import FixedWindowRateLimiter
from app.auth.tokens import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_refresh_token,
    new_refresh_token,
)

SECRET = "unit-test-signing-key-0123456789abcdef"  # noqa: S105 - test value
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def test_password_hash_is_argon2id_and_verifies() -> None:
    h = hash_password("correct horse battery")
    assert h.startswith("$argon2id$")
    assert "correct horse battery" not in h
    assert verify_password(h, "correct horse battery")
    assert not verify_password(h, "wrong horse battery")


def test_verify_unknown_user_is_false_even_for_dummy_password() -> None:
    assert not verify_password(None, "dummy-password-for-timing-equalisation")
    assert not verify_password("not-a-hash", "whatever-password")


@pytest.mark.parametrize(
    ("password", "ok"),
    [
        ("a" * (MIN_PASSWORD_LENGTH - 1), False),
        ("a" * MIN_PASSWORD_LENGTH, True),
        (" " * 20, False),
        ("x" * 129, False),
        ("x" * 128, True),
    ],
)
def test_password_policy(password: str, ok: bool) -> None:
    assert (password_policy_problem(password) is None) is ok


def _token(**kw: object) -> str:
    args: dict[str, object] = {
        "user_id": uuid.uuid4(),
        "session_id": uuid.uuid4(),
        "secret": SECRET,
        "ttl_s": 900,
        "now": NOW,
    }
    args.update(kw)
    return create_access_token(**args)[0]  # type: ignore[arg-type]


def test_access_token_round_trip() -> None:
    uid, sid = uuid.uuid4(), uuid.uuid4()
    claims = decode_access_token(
        _token(user_id=uid, session_id=sid), secret=SECRET, now=NOW + timedelta(seconds=10)
    )
    assert claims.user_id == uid and claims.session_id == sid


def test_access_token_expires() -> None:
    tok = _token(ttl_s=60)
    decode_access_token(tok, secret=SECRET, now=NOW + timedelta(seconds=59))
    with pytest.raises(InvalidTokenError):
        decode_access_token(tok, secret=SECRET, now=NOW + timedelta(seconds=60))


def test_access_token_wrong_secret_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token(_token(), secret=SECRET + "x", now=NOW)


def test_alg_none_and_wrong_type_rejected() -> None:
    payload = {
        "iss": "mediavault-api",
        "aud": "mediavault",
        "sub": str(uuid.uuid4()),
        "sid": str(uuid.uuid4()),
        "typ": "access",
        "iat": int(NOW.timestamp()),
        "exp": int(NOW.timestamp()) + 900,
    }
    none_token = jwt.encode(payload, key=None, algorithm="none")
    with pytest.raises(InvalidTokenError):
        decode_access_token(none_token, secret=SECRET, now=NOW)
    refresh_typed = jwt.encode({**payload, "typ": "refresh"}, SECRET, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode_access_token(refresh_typed, secret=SECRET, now=NOW)


def test_garbage_token_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token("not.a.jwt", secret=SECRET, now=NOW)


def test_refresh_tokens_are_random_and_hashed() -> None:
    raw1, h1 = new_refresh_token()
    raw2, h2 = new_refresh_token()
    assert raw1 != raw2 and h1 != h2
    assert len(raw1) >= 40 and len(h1) == 64
    assert hash_refresh_token(raw1) == h1 and raw1 not in h1


def test_rate_limiter_blocks_after_limit_and_resets() -> None:
    t = [1000.0]
    rl = FixedWindowRateLimiter(lambda: t[0])
    assert all(rl.hit("k", limit=3, window_s=60) is None for _ in range(3))
    retry = rl.hit("k", limit=3, window_s=60)
    assert retry is not None and 1 <= retry <= 60
    assert rl.hit("other", limit=3, window_s=60) is None  # keys are independent
    t[0] += 60
    assert rl.hit("k", limit=3, window_s=60) is None


def test_token_issued_in_the_future_rejected() -> None:
    tok = _token(now=NOW + timedelta(minutes=5))
    with pytest.raises(InvalidTokenError):
        decode_access_token(tok, secret=SECRET, now=NOW)


def _req(peer: str, xff: str | None = None):  # type: ignore[no-untyped-def]
    from starlette.requests import Request

    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def test_client_ip_ignores_x_forwarded_for_from_untrusted_peer() -> None:
    from app.api.v1.auth import client_ip

    assert client_ip(_req("203.0.113.9", "1.2.3.4"), []) == "203.0.113.9"
    assert client_ip(_req("203.0.113.9", "1.2.3.4"), ["10.0.0.5"]) == "203.0.113.9"


def test_client_ip_uses_x_forwarded_for_from_trusted_proxy() -> None:
    from app.api.v1.auth import client_ip

    assert client_ip(_req("10.0.0.5", "198.51.100.7"), ["10.0.0.5"]) == "198.51.100.7"
    # A client-supplied spoofed left-most hop is ignored; the right-most untrusted hop wins.
    assert client_ip(_req("10.0.0.5", "6.6.6.6, 198.51.100.7"), ["10.0.0.5"]) == "198.51.100.7"
    assert client_ip(_req("10.0.0.5"), ["10.0.0.5"]) == "10.0.0.5"


def test_client_ip_trusted_proxies_accept_cidr_ranges() -> None:
    from app.api.v1.auth import client_ip

    trusted = ["10.0.0.0/8", "not-an-ip"]
    assert client_ip(_req("10.1.2.3", "198.51.100.7"), trusted) == "198.51.100.7"
    # Hops inside the trusted range are skipped from the right.
    assert client_ip(_req("10.1.2.3", "198.51.100.7, 10.9.9.9"), trusted) == "198.51.100.7"
    # A peer outside the range cannot spoof, and a malformed entry never trusts anything.
    assert client_ip(_req("192.0.2.1", "198.51.100.7"), trusted) == "192.0.2.1"
    assert client_ip(_req("192.0.2.1", "198.51.100.7"), ["not-an-ip"]) == "192.0.2.1"
