"""/api/v1/auth: register, login, refresh, logout, me.

Tokens are returned in the JSON body. The website keeps them in httpOnly cookies set by its own
server-side route handlers (the browser JS never sees them); the Android app stores them
encrypted. The API itself never reads cookies, so it has no CSRF surface.
"""

import ipaddress
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.api.deps import AppSettings, CurrentUser, DbSession, Now
from app.auth import service
from app.auth.passwords import MAX_PASSWORD_LENGTH, password_policy_problem
from app.auth.tokens import InvalidTokenError, decode_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS = "Invalid email or password."
INVALID_REFRESH = "Session expired. Sign in again."
REGISTER_ACCEPTED = "If this email can be used, the account is ready. Sign in to continue."


class RegisterRequest(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)

    @field_validator("password")
    @classmethod
    def _policy(cls, value: str) -> str:
        problem = password_policy_problem(value)
        if problem:
            raise ValueError(problem)
        return value


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, max_length=512)


class MessageResponse(BaseModel):
    detail: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int
    refresh_token: str
    refresh_expires_in: int


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    is_active: bool
    created_at: datetime


def _is_trusted(host: str, trusted_proxies: list[str]) -> bool:
    """True when `host` is one of the configured proxy IPs or inside one of the CIDR ranges."""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    for entry in trusted_proxies:
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue  # ignore malformed entries rather than trusting anything
    return False


def client_ip(request: Request, trusted_proxies: list[str]) -> str:
    """The caller's IP. X-Forwarded-For is honoured only when the direct peer is trusted."""
    peer = request.client.host if request.client else "unknown"
    if not _is_trusted(peer, trusted_proxies):
        return peer
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    # Walk from the right: the first hop that is not one of our proxies is the client.
    for hop in reversed(hops):
        if not _is_trusted(hop, trusted_proxies):
            return hop
    return peer


def _rate_limit(request: Request, settings: AppSettings, scope: str, email: str | None) -> None:
    limiter = request.app.state.auth_rate_limiter
    window = settings.auth_rate_limit_window_s
    ip = client_ip(request, settings.auth_trusted_proxies)
    retry = limiter.hit(f"{scope}:ip:{ip}", limit=settings.auth_rate_limit_per_ip, window_s=window)
    if retry is None and email:
        key = f"{scope}:email:{service.normalize_email(email)}"
        retry = limiter.hit(key, limit=settings.auth_rate_limit_per_email, window_s=window)
    if retry is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(int(retry))},
        )


def _tokens(pair: service.TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=pair.access_token,
        expires_in=pair.expires_in,
        refresh_token=pair.refresh_token,
        refresh_expires_in=pair.refresh_expires_in,
    )


@router.post("/register", status_code=status.HTTP_202_ACCEPTED, response_model=MessageResponse)
async def register(
    body: RegisterRequest, request: Request, db: DbSession, settings: AppSettings
) -> MessageResponse:
    _rate_limit(request, settings, "register", body.email)
    await service.register(db, email=body.email, password=body.password)
    return MessageResponse(detail=REGISTER_ACCEPTED)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, request: Request, db: DbSession, settings: AppSettings, now: Now
) -> TokenResponse:
    _rate_limit(request, settings, "login", body.email)
    try:
        user = await service.authenticate(db, email=body.email, password=body.password)
    except service.AuthError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS) from None
    return _tokens(await service.start_session(db, user, settings=settings, now=now))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest, db: DbSession, settings: AppSettings, now: Now
) -> TokenResponse:
    try:
        pair = await service.rotate(db, body.refresh_token, settings=settings, now=now)
    except service.AuthError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=INVALID_REFRESH) from None
    return _tokens(pair)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    db: DbSession,
    settings: AppSettings,
    now: Now,
    body: LogoutRequest | None = None,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
    ] = None,
) -> Response:
    """Revoke the session named by the refresh token and/or the bearer token. Always 204."""
    session_id = None
    if credentials is not None:
        try:
            claims = decode_access_token(
                credentials.credentials, secret=settings.resolved_jwt_secret, now=now
            )
            session_id = claims.session_id
        except InvalidTokenError:
            pass
    await service.logout(
        db,
        refresh_token=body.refresh_token if body else None,
        session_id=session_id,
        now=now,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse(
        id=user.id, email=user.email, is_active=user.is_active, created_at=user.created_at
    )
