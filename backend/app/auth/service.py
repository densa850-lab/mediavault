"""Account, session and refresh-token logic. Every failure is reported generically."""

import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.auth.tokens import (
    SUCCESSOR_NONCE_BYTES,
    create_access_token,
    derive_successor_refresh_token,
    hash_refresh_token,
    new_refresh_token,
)
from app.core.config import Settings
from app.core.logging import log
from app.models import AuthSession, RefreshToken, User


class AuthError(Exception):
    """Generic authentication failure. Never says which part was wrong."""


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def register(db: AsyncSession, *, email: str, password: str) -> None:
    """Create the account if the email is free. Same outcome either way (no enumeration)."""
    password_hash = hash_password(password)  # always hash: equal timing for new/existing emails
    email = normalize_email(email)
    exists = (await db.execute(select(User.id).where(User.email == email))).scalar_one_or_none()
    if exists is not None:
        log.info("auth.register_existing_email")
        return
    db.add(User(email=email, password_hash=password_hash))
    try:
        await db.commit()
        log.info("auth.registered")
    except IntegrityError:  # concurrent registration of the same email
        await db.rollback()


async def authenticate(db: AsyncSession, *, email: str, password: str) -> User:
    user = (
        await db.execute(select(User).where(User.email == normalize_email(email)))
    ).scalar_one_or_none()
    ok = verify_password(user.password_hash if user else None, password)
    if not ok or user is None or not user.is_active:
        raise AuthError
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


def _refresh_ttl(session: AuthSession, *, settings: Settings, now: datetime) -> int:
    remaining = int((session.expires_at - now).total_seconds())
    return max(1, min(settings.refresh_token_ttl_s, remaining))


async def _issue_refresh(
    db: AsyncSession, session: AuthSession, *, settings: Settings, now: datetime
) -> tuple[str, int]:
    """A fresh random refresh token (used at login)."""
    raw, digest = new_refresh_token()
    ttl = _refresh_ttl(session, settings=settings, now=now)
    db.add(
        RefreshToken(
            session_id=session.id, token_hash=digest, expires_at=now + timedelta(seconds=ttl)
        )
    )
    return raw, ttl


def _access(session: AuthSession, *, settings: Settings, now: datetime) -> tuple[str, int]:
    return create_access_token(
        user_id=session.user_id,
        session_id=session.id,
        secret=settings.resolved_jwt_secret,
        ttl_s=settings.access_token_ttl_s,
        now=now,
    )


async def start_session(
    db: AsyncSession, user: User, *, settings: Settings, now: datetime
) -> TokenPair:
    session = AuthSession(
        id=uuid.uuid4(),
        user_id=user.id,
        expires_at=now + timedelta(seconds=settings.refresh_token_ttl_s),
    )
    db.add(session)
    await db.flush()
    raw, refresh_ttl = await _issue_refresh(db, session, settings=settings, now=now)
    access, access_ttl = _access(session, settings=settings, now=now)
    await db.commit()
    return TokenPair(access, access_ttl, raw, refresh_ttl)


async def _revoke(db: AsyncSession, session_id: uuid.UUID, *, reason: str, now: datetime) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason=reason)
    )


# Each request reads the clock when it starts, BEFORE it waits for the session lock. A racer that
# started a moment before the winner therefore sees the winner's `used_at` slightly in its future
# (negative age, MV-015). Such a request is concurrent by definition, so a small negative age is
# treated as age 0. Bounded so a badly skewed clock can't widen the grace.
MAX_RACE_CLOCK_SKEW_S = 5.0


def _within_grace(token: RefreshToken, *, settings: Settings, now: datetime) -> bool:
    grace = settings.refresh_reuse_grace_s
    if grace <= 0 or token.used_at is None:
        return False
    age = (now - token.used_at).total_seconds()
    return -MAX_RACE_CLOCK_SKEW_S <= age <= grace


async def _grace_successor(
    db: AsyncSession,
    token: RefreshToken,
    raw: str,
    session: AuthSession,
    *,
    settings: Settings,
    now: datetime,
) -> TokenPair | None:
    """Concurrency grace: the same successor for a token rotated moments ago, else None.

    Only for the token's DIRECT successor, only while that successor is unused and unexpired,
    only within `refresh_reuse_grace_s` of the rotation, and only in the same session. The
    successor is re-derived from the presented raw token (see derive_successor_refresh_token)
    and must match its stored hash.
    """
    if token.replaced_by_id is None or token.successor_nonce is None:
        return None
    if not _within_grace(token, settings=settings, now=now):
        return None
    successor = (
        await db.execute(
            select(RefreshToken)
            .where(RefreshToken.id == token.replaced_by_id)
            .where(RefreshToken.session_id == session.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if successor is None or successor.used_at is not None or successor.expires_at <= now:
        return None
    succ_raw, succ_digest = derive_successor_refresh_token(
        raw, nonce=token.successor_nonce, session_id=session.id, successor_id=successor.id
    )
    if not hmac.compare_digest(succ_digest, successor.token_hash):
        return None
    access, access_ttl = _access(session, settings=settings, now=now)
    refresh_ttl = max(1, int((successor.expires_at - now).total_seconds()))
    return TokenPair(access, access_ttl, succ_raw, refresh_ttl)


async def rotate(db: AsyncSession, raw: str, *, settings: Settings, now: datetime) -> TokenPair:
    """Exchange a refresh token for a new pair.

    Single use with reuse detection: presenting an already-used token revokes the whole session,
    EXCEPT the bounded concurrency grace (`_grace_successor`): re-presenting the token that was
    rotated less than `refresh_reuse_grace_s` ago, whose successor has not been used yet, returns
    that same successor (with a fresh access token) so that two overlapping refreshes from the
    same client do not log the user out.

    Locking: the session row is locked first, then the token rows, so every rotation of one
    session is serialised and lock order is the same everywhere (no deadlocks).
    """
    digest = hash_refresh_token(raw)
    session_id = (
        await db.execute(select(RefreshToken.session_id).where(RefreshToken.token_hash == digest))
    ).scalar_one_or_none()
    if session_id is None:
        raise AuthError
    session = (
        await db.execute(
            select(AuthSession).where(AuthSession.id == session_id).with_for_update(of=AuthSession)
        )
    ).scalar_one()
    if session.revoked_at is not None or session.expires_at <= now:
        raise AuthError
    token = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == digest).with_for_update()
        )
    ).scalar_one()
    if not session.user.is_active:
        raise AuthError
    if token.used_at is not None:
        pair = await _grace_successor(db, token, raw, session, settings=settings, now=now)
        if pair is not None:
            await db.commit()
            log.info("auth.refresh_grace_reissue", session_id=str(session.id))
            return pair
        # Reuse of a rotated token outside the grace case: it may have been stolen.
        await _revoke(db, session.id, reason="refresh_reuse", now=now)
        await db.commit()
        log.warning("auth.refresh_reuse_detected", session_id=str(session.id))
        raise AuthError
    if token.expires_at <= now:
        raise AuthError

    nonce = secrets.token_bytes(SUCCESSOR_NONCE_BYTES)
    successor_id = uuid.uuid4()
    succ_raw, succ_digest = derive_successor_refresh_token(
        raw, nonce=nonce, session_id=session.id, successor_id=successor_id
    )
    refresh_ttl = _refresh_ttl(session, settings=settings, now=now)
    db.add(
        RefreshToken(
            id=successor_id,
            session_id=session.id,
            token_hash=succ_digest,
            expires_at=now + timedelta(seconds=refresh_ttl),
        )
    )
    await db.flush()
    token.used_at = now
    token.replaced_by_id = successor_id
    token.successor_nonce = nonce
    # This token is now used, so its predecessor can never be granted it again: drop that nonce.
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.replaced_by_id == token.id)
        .values(successor_nonce=None)
    )
    access, access_ttl = _access(session, settings=settings, now=now)
    await db.commit()
    return TokenPair(access, access_ttl, succ_raw, refresh_ttl)


async def logout(
    db: AsyncSession,
    *,
    refresh_token: str | None,
    session_id: uuid.UUID | None,
    now: datetime,
) -> bool:
    """Revoke the named session(s). Returns False when nothing valid was named."""
    ids: set[uuid.UUID] = set()
    if session_id is not None:
        ids.add(session_id)
    if refresh_token:
        sid = (
            await db.execute(
                select(RefreshToken.session_id).where(
                    RefreshToken.token_hash == hash_refresh_token(refresh_token)
                )
            )
        ).scalar_one_or_none()
        if sid is not None:
            ids.add(sid)
    for sid in ids:
        await _revoke(db, sid, reason="logout", now=now)
    await db.commit()
    return bool(ids)
