"""Stress test for MV-015: real, unsynchronised concurrent refreshes over HTTP.

For each race: log in (new session), then N threads released by a barrier POST /auth/refresh with
the SAME refresh token at the same moment, each on its own connection. Every response must be 200
with one shared successor, and no session may be revoked.

Usage (against a running API whose login limits allow the number of logins):
    STRESS_API=http://127.0.0.1:8000 STRESS_DB_URL=postgresql://... \\
        uv run python scripts/stress_refresh_races.py --two-way 120 --five-way 25

STRESS_DB_URL (optional) is used read-only to count revoked sessions; it is never printed.
Exit code 0 only if every race kept its session.
"""

import argparse
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter


def _post(base: str, path: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(  # noqa: S310 - URL from the operator's environment
        f"{base}/api/v1{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:  # noqa: S310
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def _race(base: str, refresh_token: str, n: int) -> list[tuple[int, dict]]:
    barrier = threading.Barrier(n)
    results: list[tuple[int, dict]] = [(0, {})] * n

    def run(i: int) -> None:
        barrier.wait()
        results[i] = _post(base, "/auth/refresh", {"refresh_token": refresh_token})

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def _revoked_sessions(db_url: str | None, user_email: str) -> int | None:
    if not db_url:
        return None
    import psycopg

    with psycopg.connect(db_url.replace("+psycopg", "")) as conn:
        row = conn.execute(
            "SELECT count(*) FROM auth_sessions s JOIN users u ON u.id = s.user_id "
            "WHERE u.email = %s AND s.revoked_at IS NOT NULL",
            (user_email,),
        ).fetchone()
        return int(row[0]) if row else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--two-way", type=int, default=100)
    parser.add_argument("--five-way", type=int, default=20)
    args = parser.parse_args()
    base = os.environ.get("STRESS_API", "http://127.0.0.1:8000").rstrip("/")
    db_url = os.environ.get("STRESS_DB_URL")

    email = f"stress.{secrets.token_hex(4)}@example.com"
    password = secrets.token_urlsafe(18)
    status, _ = _post(base, "/auth/register", {"email": email, "password": password})
    assert status == 202, status

    totals: Counter[str] = Counter()
    failures: list[str] = []
    start = time.monotonic()
    for n, rounds in ((2, args.two_way), (5, args.five_way)):
        for r in range(rounds):
            status, tokens = _post(base, "/auth/login", {"email": email, "password": password})
            if status != 200:
                failures.append(f"{n}-way #{r}: login {status}")
                continue
            results = _race(base, tokens["refresh_token"], n)
            codes = [c for c, _ in results]
            successors = {b.get("refresh_token") for c, b in results if c == 200}
            ok = codes == [200] * n and len(successors) == 1
            totals[f"{n}-way {'ok' if ok else 'FAIL'}"] += 1
            totals.update(f"status {c}" for c in codes)
            if not ok:
                failures.append(f"{n}-way #{r}: codes={codes} successors={len(successors)}")
                continue
            # The shared successor must still be live (session not revoked).
            status, _ = _post(base, "/auth/refresh", {"refresh_token": successors.pop()})
            if status != 200:
                failures.append(f"{n}-way #{r}: successor refresh {status}")
    elapsed = time.monotonic() - start
    revoked = _revoked_sessions(db_url, email)

    print(f"races: two-way={args.two_way} five-way={args.five_way} in {elapsed:.1f}s")
    for key in sorted(totals):
        print(f"  {key}: {totals[key]}")
    print(f"failures: {len(failures)}")
    for f in failures[:50]:
        print(f"  {f}")
    shown = revoked if revoked is not None else "n/a"
    print(f"revoked sessions in DB for the stress user: {shown}")
    passed = not failures and (revoked in (0, None))
    print("RESULT:", "PASS (zero revocations)" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
