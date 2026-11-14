"""Shared request dependencies: DB session, clock and the authenticated user."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import InvalidTokenError, decode_access_token
from app.core.config import Settings
from app.models import AuthSession, User

_bearer = HTTPBearer(auto_error=False)

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_now(request: Request) -> datetime:
    return request.app.state.clock()


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]
Now = Annotated[datetime, Depends(get_now)]
AppSettings = Annotated[Settings, Depends(get_settings_dep)]


async def get_current_session(
    db: DbSession,
    now: Now,
    settings: AppSettings,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthSession:
    """Validate the bearer access token AND its server-side session (so logout is immediate)."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UNAUTHORIZED
    try:
        claims = decode_access_token(
            credentials.credentials, secret=settings.resolved_jwt_secret, now=now
        )
    except InvalidTokenError:
        raise UNAUTHORIZED from None
    session = (
        await db.execute(select(AuthSession).where(AuthSession.id == claims.session_id))
    ).scalar_one_or_none()
    if (
        session is None
        or session.user_id != claims.user_id
        or session.revoked_at is not None
        or session.expires_at <= now
        or not session.user.is_active
    ):
        raise UNAUTHORIZED
    return session


CurrentSession = Annotated[AuthSession, Depends(get_current_session)]


async def get_current_user(session: CurrentSession) -> User:
    return session.user


CurrentUser = Annotated[User, Depends(get_current_user)]
