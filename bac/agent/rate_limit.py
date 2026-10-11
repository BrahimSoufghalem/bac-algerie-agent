"""Process-local, cancellable input pacing. Estimates are NOT billable token usage.

Reservations persist across event loops. Multiple worker processes need a shared
operator quota; this conservative guard cannot guarantee a provider-wide limit.
No prompt truncation, hidden retries, source cap or provider quota bypass.
"""

import asyncio
from collections import deque
import hashlib
import json
import threading
import time
from urllib.parse import urlsplit


class InputPacer:
    def __init__(self, clock=time.monotonic, sleep=asyncio.sleep):
        self.clock, self.sleep = clock, sleep
        self.lock = threading.Lock()
        self.entries = deque()
        self.cooldown_until = 0.0
        self.sequence = 0

    async def reserve(self, estimated, limit):
        while True:
            with self.lock:
                now = self.clock()
                while self.entries and now - self.entries[0][1] >= 60:
                    self.entries.popleft()
                delay = max(0.0, self.cooldown_until - now)
                # A request bigger than the pacing budget is allowed ALONE, not
                # truncated or stalled forever. Provider hard limits still apply.
                if self.entries and sum(e[2] for e in self.entries) + estimated > limit:
                    delay = max(delay, self.entries[0][1] + 60 - now)
                if delay <= 0:
                    self.sequence += 1
                    entry = [self.sequence, now, estimated]
                    self.entries.append(entry)
                    return entry
            await self.sleep(delay)

    def settle(self, reservation, actual):
        if type(actual) is int and actual >= 0:
            with self.lock:
                reservation[2] = actual
        # Unknown remains conservatively estimated, never reported as measured zero.

    def rate_limited(self, delay):
        delay = delay if type(delay) in {int, float} and 0 <= delay <= 3600 else 60
        with self.lock:
            self.cooldown_until = max(self.cooldown_until, self.clock() + delay)


_PACERS = {}
_LOCK = threading.Lock()


def input_pacer(cfg, key, transport=None):
    host = (urlsplit(cfg.get("base_url", "")).hostname or "").lower()
    google = host == "generativelanguage.googleapis.com"
    limit = cfg.get("input_tokens_per_minute")
    # Deterministic HTTP mock unit tests have no remote quota. Explicit limits
    # still permit exercising pacing with MockTransport.
    import httpx

    if limit is None:
        limit = (
            200000 if google and not isinstance(transport, httpx.MockTransport) else 0
        )
    if type(limit) is not int or limit <= 0:
        return None, 0
    model = cfg.get("model", "").removeprefix("models/")
    identity = (
        "google" if google else cfg.get("base_url", "").rstrip("/"),
        model,
        hashlib.sha256(key.encode()).digest(),
    )
    with _LOCK:
        if identity not in _PACERS:
            if len(_PACERS) >= 256:
                # Fail closed rather than evict live quota state. Small bounded map.
                raise ValueError(
                    "Too many active provider pacing identities; restart worker after config cleanup"
                )
            _PACERS[identity] = InputPacer()
        return _PACERS[identity], limit


async def reserve_input(cfg, key, body, transport=None):
    pacer, limit = input_pacer(cfg, key, transport)
    if pacer is None:
        return None, None
    # Conservative heuristic only. Actual provider counts replace it when known.
    estimate = (
        len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()) + 1
    ) // 2
    return pacer, await pacer.reserve(estimate, limit)
