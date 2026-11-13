"""In-memory fixed-window rate limiter for login/register.

Limits are per process: with several API workers or replicas each keeps its own counters, so
the effective limit is multiplied. Moving the counters to Redis (already in the dev stack) is the
planned upgrade before running more than one worker. Behind a reverse proxy, run uvicorn with
--proxy-headers and --forwarded-allow-ips set to the proxy, otherwise every client shares the
proxy's IP.
"""

import math
from collections.abc import Callable


class FixedWindowRateLimiter:
    def __init__(self, clock: Callable[[], float], max_keys: int = 100_000) -> None:
        self._clock = clock
        self._max_keys = max_keys
        self._windows: dict[str, tuple[float, int]] = {}

    def hit(self, key: str, *, limit: int, window_s: int) -> float | None:
        """Count one attempt. Returns None if allowed, else seconds until the window resets."""
        now = self._clock()
        start, count = self._windows.get(key, (now, 0))
        if now - start >= window_s:
            start, count = now, 0
        count += 1
        if len(self._windows) >= self._max_keys and key not in self._windows:
            self._evict(now, window_s)
        self._windows[key] = (start, count)
        if count > limit:
            return max(1.0, math.ceil(start + window_s - now))
        return None

    def _evict(self, now: float, window_s: int) -> None:
        expired = [k for k, (start, _) in self._windows.items() if now - start >= window_s]
        for k in expired:
            del self._windows[k]
        if len(self._windows) >= self._max_keys:
            self._windows.clear()

    def reset(self) -> None:
        self._windows.clear()
