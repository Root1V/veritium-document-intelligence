"""Calls per minute per connected system (VRT-65): a fixed one-minute window
per client, in memory — each API process counts its own calls, so with N
processes a client gets up to N times its quota. Enough to stop a system
that loops by mistake; a shared limit belongs with the gateway in front."""

from __future__ import annotations

import math
import time

_WINDOW = 60.0


class RateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, tuple[float, int]] = {}

    def check(self, key: str, limit: int, *, now: float | None = None) -> int | None:
        """Counts a call. Returns None if allowed, else the seconds until the window resets."""
        now = time.monotonic() if now is None else now
        start, count = self._windows.get(key, (now, 0))
        if now - start >= _WINDOW:
            start, count = now, 0
        if count >= limit:
            return max(1, math.ceil(_WINDOW - (now - start)))
        self._windows[key] = (start, count + 1)
        return None


limiter = RateLimiter()
