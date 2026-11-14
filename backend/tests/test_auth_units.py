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
from tests.conftest import make_settings

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


def _req(peer: str, xff: str | None = None, named: str | None = None):  # type: ignore[no-untyped-def]
    from starlette.requests import Request

    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    if named is not None:
        headers.append((b"x-mediavault-client-ip", named.encode()))
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def test_client_ip_ignores_forwarding_headers_from_untrusted_peer() -> None:
    from app.api.v1.auth import UNTRUSTED_FORWARDED, client_ip

    assert client_ip(_req("203.0.113.9"), []) == "203.0.113.9"
    # MV-016: an untrusted peer that claims an address is never believed, and every such request
    # shares ONE bucket, whatever address it claims.
    # MV-025: keyed on the real peer, not one global bucket other clients share.
    keyed = f"{UNTRUSTED_FORWARDED}:203.0.113.9"
    assert client_ip(_req("203.0.113.9", "1.2.3.4"), []) == keyed
    assert client_ip(_req("203.0.113.9", "1.2.3.4"), ["10.0.0.5"]) == keyed
    assert client_ip(_req("203.0.113.9", named="1.2.3.4"), ["10.0.0.5"]) == keyed
    # Another untrusted client is in its own bucket.
    assert client_ip(_req("203.0.113.10", "1.2.3.4"), []) == f"{UNTRUSTED_FORWARDED}:203.0.113.10"


def test_client_ip_rotating_x_forwarded_for_maps_to_one_key() -> None:
    from app.api.v1.auth import client_ip

    for trusted in ([], ["10.0.0.5"]):
        keys = {client_ip(_req("127.0.0.1", f"198.51.100.{i}"), trusted) for i in range(50)}
        assert len(keys) == 1, keys


def test_client_ip_survives_uvicorn_proxy_header_rewriting() -> None:
    """If uvicorn runs WITH proxy headers (its default trusts 127.0.0.1), it replaces the peer
    with the X-Forwarded-For address before the app sees it. Rotating XFF from loopback then looks
    like many different peers; they must still share one bucket (MV-016)."""
    from app.api.v1.auth import client_ip

    keys = {client_ip(_req(f"198.51.100.{i}", f"198.51.100.{i}"), []) for i in range(50)}
    assert len(keys) == 1, keys
    # uvicorn picks the right-most UNtrusted hop, so "X, 127.0.0.1" rewrites the peer to X.
    keys = {client_ip(_req(f"198.51.100.{i}", f"198.51.100.{i}, 127.0.0.1"), []) for i in range(50)}
    assert len(keys) == 1, keys


def test_client_ip_uses_x_forwarded_for_from_trusted_proxy() -> None:
    from app.api.v1.auth import client_ip

    assert client_ip(_req("10.0.0.5", "198.51.100.7"), ["10.0.0.5"]) == "198.51.100.7"
    # Only the right-most untrusted hop counts; the client-controlled left part is ignored.
    assert client_ip(_req("10.0.0.5", "6.6.6.6, 198.51.100.7"), ["10.0.0.5"]) == "198.51.100.7"
    assert client_ip(_req("10.0.0.5"), ["10.0.0.5"]) == "10.0.0.5"


def test_client_ip_header_from_trusted_proxy_wins_over_x_forwarded_for() -> None:
    from app.api.v1.auth import client_ip

    trusted = ["127.0.0.1"]
    req = _req("127.0.0.1", "6.6.6.6", named="198.51.100.7")
    assert client_ip(req, trusted) == "198.51.100.7"
    # A malformed header is ignored (falls back to XFF / peer), never used as a key verbatim.
    assert client_ip(_req("127.0.0.1", named="not-an-ip"), trusted) == "127.0.0.1"
    assert client_ip(_req("127.0.0.1", named="2001:db8::1"), trusted) == "2001:db8::1"


def test_client_ip_trusted_proxies_accept_cidr_ranges() -> None:
    from app.api.v1.auth import UNTRUSTED_FORWARDED, client_ip

    trusted = ["10.0.0.0/8"]
    assert client_ip(_req("10.1.2.3", "198.51.100.7"), trusted) == "198.51.100.7"
    # Trusted hops inside the chain are skipped.
    assert client_ip(_req("10.1.2.3", "198.51.100.7, 10.9.9.9"), trusted) == "198.51.100.7"
    # Peers outside the range are not trusted.
    assert (
        client_ip(_req("192.0.2.1", "198.51.100.7"), trusted) == f"{UNTRUSTED_FORWARDED}:192.0.2.1"
    )
    untrusted_cfg = client_ip(_req("192.0.2.1", "198.51.100.7"), ["not-an-ip"])
    assert untrusted_cfg == f"{UNTRUSTED_FORWARDED}:192.0.2.1"


def test_rate_limiter_retry_after_peeks_without_counting() -> None:
    t = [1000.0]
    rl = FixedWindowRateLimiter(lambda: t[0])
    for _ in range(10):
        assert rl.retry_after("k", limit=2, window_s=60) is None
    rl.hit("k", limit=2, window_s=60)
    assert rl.retry_after("k", limit=2, window_s=60) is None
    rl.hit("k", limit=2, window_s=60)
    retry = rl.retry_after("k", limit=2, window_s=60)
    assert retry is not None and 1 <= retry <= 60
    t[0] += 60
    assert rl.retry_after("k", limit=2, window_s=60) is None


def _used(seconds_ago: float):  # type: ignore[no-untyped-def]
    from app.models import RefreshToken

    return RefreshToken(used_at=NOW - timedelta(seconds=seconds_ago))


@pytest.mark.parametrize(
    ("used_seconds_ago", "within"),
    [
        (0, True),
        (5, True),
        (10, True),
        (10.001, False),
        # MV-015: the losing racer read its clock BEFORE the winner rotated (negative age).
        (-0.000001, True),
        (-0.25, True),
        (-5, True),
        (-5.001, False),
        (-3600, False),
    ],
)
def test_within_grace_tolerates_small_negative_age(used_seconds_ago: float, within: bool) -> None:
    from app.auth.service import _within_grace

    settings = make_settings(refresh_reuse_grace_s=10)
    assert _within_grace(_used(used_seconds_ago), settings=settings, now=NOW) is within


def test_within_grace_zero_disables_even_for_racers() -> None:
    from app.auth.service import _within_grace

    settings = make_settings(refresh_reuse_grace_s=0)
    assert _within_grace(_used(-0.1), settings=settings, now=NOW) is False
    assert _within_grace(_used(0), settings=settings, now=NOW) is False


def test_successor_derivation_requires_the_predecessor_token_and_nonce() -> None:
    import uuid

    from app.auth.tokens import derive_successor_refresh_token, hash_refresh_token

    sid, succ_id = uuid.uuid4(), uuid.uuid4()
    nonce = b"\x01" * 32
    raw, digest = derive_successor_refresh_token(
        "old-token", nonce=nonce, session_id=sid, successor_id=succ_id
    )
    assert digest == hash_refresh_token(raw) and len(raw) >= 43  # 256-bit, url-safe
    again, _ = derive_successor_refresh_token(
        "old-token", nonce=nonce, session_id=sid, successor_id=succ_id
    )
    assert again == raw  # deterministic for the holder of the old token
    others = {
        derive_successor_refresh_token(
            "other-token", nonce=nonce, session_id=sid, successor_id=succ_id
        )[0],
        derive_successor_refresh_token(
            "old-token", nonce=b"\x02" * 32, session_id=sid, successor_id=succ_id
        )[0],
        derive_successor_refresh_token(
            "old-token", nonce=nonce, session_id=uuid.uuid4(), successor_id=succ_id
        )[0],
        derive_successor_refresh_token(
            "old-token", nonce=nonce, session_id=sid, successor_id=uuid.uuid4()
        )[0],
    }
    assert raw not in others and len(others) == 4


@pytest.mark.parametrize("value", [-1, 61])
def test_refresh_grace_is_bounded(value: int) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_settings(refresh_reuse_grace_s=value)


def test_refresh_grace_default_is_short() -> None:
    assert 0 < make_settings().refresh_reuse_grace_s <= 30
