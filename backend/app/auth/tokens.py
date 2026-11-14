"""Access tokens (short-lived HS256 JWT) and opaque refresh tokens (stored only as SHA-256)."""

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

import jwt

ALGORITHM = "HS256"
ISSUER = "mediavault-api"
AUDIENCE = "mediavault"
MAX_CLOCK_SKEW_S = 60


class InvalidTokenError(Exception):
    """The token is malformed, has a bad signature, the wrong type, or has expired."""


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    expires_at: int


def create_access_token(
    *, user_id: uuid.UUID, session_id: uuid.UUID, secret: str, ttl_s: int, now: datetime
) -> tuple[str, int]:
    iat = int(now.timestamp())
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user_id),
        "sid": str(session_id),
        "typ": "access",
        "iat": iat,
        "exp": iat + ttl_s,
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM), ttl_s


def decode_access_token(token: str, *, secret: str, now: datetime) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],  # pinned: no "none", no algorithm confusion
            audience=AUDIENCE,
            issuer=ISSUER,
            # exp/iat are checked below against the app clock (testable), not time.time().
            options={
                "require": ["exp", "iat", "sub", "sid", "typ"],
                "verify_exp": False,
                "verify_iat": False,
            },
        )
        if payload.get("typ") != "access":
            raise InvalidTokenError("wrong token type")
        exp, iat, ts = int(payload["exp"]), int(payload["iat"]), int(now.timestamp())
        if exp <= ts:
            raise InvalidTokenError("expired")
        if iat > ts + MAX_CLOCK_SKEW_S:
            raise InvalidTokenError("issued in the future")
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]), session_id=uuid.UUID(payload["sid"]), expires_at=exp
        )
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise InvalidTokenError(type(exc).__name__) from exc


def new_refresh_token() -> tuple[str, str]:
    """Return (raw token for the client, sha256 hex to store)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


SUCCESSOR_NONCE_BYTES = 32


def derive_successor_refresh_token(
    predecessor_raw: str, *, nonce: bytes, session_id: uuid.UUID, successor_id: uuid.UUID
) -> tuple[str, str]:
    """The successor refresh token of `predecessor_raw`, as (raw, sha256 hex).

    HMAC-SHA256 keyed with the predecessor's raw token over a 256-bit random server-side nonce and
    the session/successor ids. Only a holder of the predecessor token can recompute it, and only
    while the server still keeps the nonce (the concurrency grace window). The database holds the
    nonce and hashes, never a raw refresh token, and the nonce alone cannot produce the successor.
    """
    msg = b"mediavault/refresh-successor/v1|" + nonce + session_id.bytes + successor_id.bytes
    digest = hmac.new(predecessor_raw.encode("utf-8"), msg, hashlib.sha256).digest()
    raw = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return raw, hash_refresh_token(raw)
