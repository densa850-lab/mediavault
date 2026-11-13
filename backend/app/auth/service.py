"""Account, session and refresh-token logic. Every failure is reported generically."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.auth.tokens import create_access_token, hash_refresh_token, new_refresh_token
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


async def _issue_refresh(
    db: AsyncSession, session: AuthSession, *, settings: Settings, now: datetime
) -> tuple[str, int]:
    raw, digest = new_refresh_token()
    remaining = int((session.expires_at - now).total_seconds())
    ttl = max(1, min(settings.refresh_token_ttl_s, remaining))
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


async def rotate(db: AsyncSession, raw: str, *, settings: Settings, now: datetime) -> TokenPair:
    """Exchange a refresh token for a new pair. A second use of any token revokes the session."""
    token = (
        await db.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_refresh_token(raw))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if token is None:
        raise AuthError
    session = (
        await db.execute(
            select(AuthSession)
            .where(AuthSession.id == token.session_id)
            .with_for_update(of=AuthSession)
        )
    ).scalar_one()
    if session.revoked_at is not None or session.expires_at <= now:
        raise AuthError
    if token.used_at is not None:
        # Reuse of a rotated token: it may have been stolen. Kill the whole session.
        await _revoke(db, session.id, reason="refresh_reuse", now=now)
        await db.commit()
        log.warning("auth.refresh_reuse_detected", session_id=str(session.id))
        raise AuthError
    if token.expires_at <= now or not session.user.is_active:
        raise AuthError
    token.used_at = now
    new_raw, refresh_ttl = await _issue_refresh(db, session, settings=settings, now=now)
    access, access_ttl = _access(session, settings=settings, now=now)
    await db.commit()
    return TokenPair(access, access_ttl, new_raw, refresh_ttl)


async def logout(
    db: AsyncSession,
    *,
    refresh_token: str | None,
    session_id: uuid.UUID | None,
    now: datetime,
) -> None:
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
