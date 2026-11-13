"""Two concurrent refreshes with the same token: exactly one may win (row lock)."""

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.auth import service
from app.db.session import create_engine, create_sessionmaker
from tests.conftest import make_settings
from tests.test_auth import A, login, register


def test_concurrent_refresh_with_same_token(db_client: TestClient) -> None:
    register(db_client, A)
    raw = login(db_client, A)["refresh_token"]
    settings = make_settings()

    async def race() -> list[object]:
        engine = create_engine(settings)
        maker = create_sessionmaker(engine)
        now = datetime.now(UTC)

        async def one() -> object:
            async with maker() as db:
                try:
                    return await service.rotate(db, raw, settings=settings, now=now)
                except service.AuthError as exc:
                    return exc

        try:
            return list(await asyncio.gather(one(), one()))
        finally:
            await engine.dispose()

    results = asyncio.run(race())
    wins = [r for r in results if isinstance(r, service.TokenPair)]
    losses = [r for r in results if isinstance(r, service.AuthError)]
    assert len(wins) == 1 and len(losses) == 1
    # The loser presented an already-used token, so reuse detection revoked the session.
    winner = wins[0]
    assert isinstance(winner, service.TokenPair)
    res = db_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {winner.access_token}"}
    )
    assert res.status_code == 401
