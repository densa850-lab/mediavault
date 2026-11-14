"""Truly concurrent refreshes with the same refresh token (separate PostgreSQL connections).

Two tabs / overlapping app requests present the same refresh token at the same moment. The
first rotates it; the others, serialised by the session row lock, must receive the SAME
successor (concurrency grace) instead of triggering reuse detection and logging the user out.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import service
from app.db.session import create_engine, create_sessionmaker
from tests.conftest import make_settings
from tests.test_auth import A, auth, login, register, sql

Clock = datetime | list[datetime | None] | None


async def _race(raw: str, n: int, now: Clock, hold_session_lock: bool) -> list[object]:
    """Run `n` rotations of `raw` concurrently, each on its own connection.

    `now`: one timestamp for every racer, a list with one per racer, or None. None means the racer
    reads the real clock itself right before it starts, exactly like a request does in deps.get_now
    (before it waits for the session lock), so racers' timestamps differ (MV-015).
    """
    settings = make_settings()
    engine = create_engine(settings)
    maker = create_sessionmaker(engine)
    nows = now if isinstance(now, list) else [now] * n
    assert len(nows) == n

    async def one(i: int) -> object:
        async with maker() as db:
            at = nows[i] or datetime.now(UTC)
            try:
                return await service.rotate(db, raw, settings=settings, now=at)
            except service.AuthError as exc:
                return exc

    try:
        if not hold_session_lock:
            return list(await asyncio.gather(*(one(i) for i in range(n))))
        # Hold the session row lock so every rotation is provably in flight at the same time,
        # then release it and let them all proceed.
        async with maker() as blocker:
            await blocker.execute(text("SELECT id FROM auth_sessions FOR UPDATE"))
            tasks = [asyncio.create_task(one(i)) for i in range(n)]
            await asyncio.sleep(0.5)
            assert not any(t.done() for t in tasks), "rotations should be waiting on the lock"
            waiting = (
                await blocker.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE wait_event_type = 'Lock' AND datname = current_database()"
                    )
                )
            ).scalar_one()
            assert waiting >= n
            await blocker.rollback()
        return list(await asyncio.gather(*tasks))
    finally:
        await engine.dispose()


def _assert_all_same_successor(results: list[object]) -> service.TokenPair:
    pairs = [r for r in results if isinstance(r, service.TokenPair)]
    assert len(pairs) == len(results), results  # nobody was logged out
    assert len({p.refresh_token for p in pairs}) == 1  # one successor, not several branches
    return pairs[0]


def test_two_truly_concurrent_refreshes_keep_session(db_client: TestClient) -> None:
    register(db_client, A)
    tokens = login(db_client, A)
    other_session = login(db_client, A)
    now = datetime.now(UTC)
    results = asyncio.run(_race(tokens["refresh_token"], 2, now, hold_session_lock=True))
    pair = _assert_all_same_successor(results)
    assert sql("SELECT count(*) FROM auth_sessions WHERE revoked_at IS NOT NULL")[0][0] == 0
    for p in results:
        assert isinstance(p, service.TokenPair)
        me = db_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {p.access_token}"})
        assert me.status_code == 200
    # The shared successor is the live token: it rotates normally.
    nxt = db_client.post("/api/v1/auth/refresh", json={"refresh_token": pair.refresh_token})
    assert nxt.status_code == 200
    assert db_client.get("/api/v1/auth/me", headers=auth(other_session)).status_code == 200


def test_many_concurrent_refreshes_keep_session(db_client: TestClient) -> None:
    register(db_client, A)
    tokens = login(db_client, A)
    results = asyncio.run(_race(tokens["refresh_token"], 8, datetime.now(UTC), False))
    _assert_all_same_successor(results)
    assert sql("SELECT revoked_at FROM auth_sessions")[0][0] is None
    # Exactly one successor row was created for the 8 overlapping refreshes.
    assert sql("SELECT count(*) FROM refresh_tokens")[0][0] == 2


def test_replay_after_grace_still_revokes_but_not_other_sessions(db_client: TestClient) -> None:
    register(db_client, A)
    tokens = login(db_client, A)
    other_session = login(db_client, A)
    now = datetime.now(UTC)
    results = asyncio.run(_race(tokens["refresh_token"], 2, now, hold_session_lock=False))
    pair = _assert_all_same_successor(results)
    grace = make_settings().refresh_reuse_grace_s
    late = now + timedelta(seconds=grace + 1)
    replay = asyncio.run(_race(tokens["refresh_token"], 1, late, hold_session_lock=False))
    assert isinstance(replay[0], service.AuthError)
    me = db_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {pair.access_token}"})
    assert me.status_code == 401
    assert (
        sql("SELECT count(*) FROM auth_sessions WHERE revoked_reason = 'refresh_reuse'")[0][0] == 1
    )
    assert db_client.get("/api/v1/auth/me", headers=auth(other_session)).status_code == 200


# ---------- MV-015: racers whose clocks were read at slightly different moments ----------


def _revoked() -> int:
    return sql("SELECT count(*) FROM auth_sessions WHERE revoked_at IS NOT NULL")[0][0]


def test_losing_racer_with_earlier_clock_keeps_session(db_client: TestClient) -> None:
    """Deterministic MV-015 reproduction: the loser's `now` is BEFORE the winner's used_at."""
    register(db_client, A)
    tokens = login(db_client, A)
    t = datetime.now(UTC)
    winner = asyncio.run(_race(tokens["refresh_token"], 1, t, hold_session_lock=False))
    for skew_ms in (1, 250, 2000):
        loser = asyncio.run(
            _race(
                tokens["refresh_token"],
                1,
                t - timedelta(milliseconds=skew_ms),
                hold_session_lock=False,
            )
        )
        assert isinstance(loser[0], service.TokenPair), (skew_ms, loser)
        assert isinstance(winner[0], service.TokenPair)
        assert loser[0].refresh_token == winner[0].refresh_token
    assert _revoked() == 0


def test_racers_with_different_timestamps_all_get_the_successor(db_client: TestClient) -> None:
    register(db_client, A)
    tokens = login(db_client, A)
    t = datetime.now(UTC)
    offsets_ms = [0, -200, 150, -1000, -1]
    nows: list[datetime | None] = [t + timedelta(milliseconds=o) for o in offsets_ms]
    results = asyncio.run(_race(tokens["refresh_token"], 5, nows, hold_session_lock=True))
    _assert_all_same_successor(results)
    assert _revoked() == 0


def test_unsynchronised_real_clock_races_never_revoke(db_client: TestClient) -> None:
    """Many real races where every racer reads its own clock (CI-sized; the stress script in
    scripts/stress_refresh_races.py runs 100+ two-way and 20+ five-way races over HTTP)."""
    register(db_client, A)
    for n, rounds in ((2, 25), (5, 8)):
        for _ in range(rounds):
            tokens = login(db_client, A)
            results = asyncio.run(_race(tokens["refresh_token"], n, None, False))
            _assert_all_same_successor(results)
    assert _revoked() == 0


def test_replay_beyond_skew_tolerance_before_use_still_revokes(db_client: TestClient) -> None:
    """The negative-age tolerance is bounded: a 'now' far before used_at is not concurrency."""
    register(db_client, A)
    tokens = login(db_client, A)
    t = datetime.now(UTC)
    asyncio.run(_race(tokens["refresh_token"], 1, t, hold_session_lock=False))
    replay = asyncio.run(
        _race(tokens["refresh_token"], 1, t - timedelta(seconds=30), hold_session_lock=False)
    )
    assert isinstance(replay[0], service.AuthError)
    assert _revoked() == 1
