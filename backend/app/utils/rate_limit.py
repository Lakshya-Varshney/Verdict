"""Rate limiting: Redis sliding-window log when REDIS_URL is set, in-memory sliding window otherwise.

The in-memory fallback keeps ``docker compose up`` working offline / without Redis, and is what the
test-suite uses. If Redis is configured but unreachable we degrade to memory instead of failing open.
"""

import logging
import secrets
import time
from collections import defaultdict
from typing import Optional

from app.config import settings

log = logging.getLogger(__name__)


class InMemoryRateLimiter:
    """Simple in-memory sliding window rate limiter (single process)."""

    def __init__(self):
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        return self.check(key, max_requests, window_seconds)[0]

    def check(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.time()
        cutoff = now - window_seconds
        recent = [t for t in self._requests[key] if t > cutoff]
        if len(recent) < max_requests:
            recent.append(now)
            self._requests[key] = recent
            return True, 0
        self._requests[key] = recent
        return False, max(1, int(recent[0] + window_seconds - now) + 1)

    def peek(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        """(blocked, retry_after) WITHOUT counting this call."""
        now = time.time()
        recent = [t for t in self._requests[key] if t > now - window_seconds]
        if len(recent) < max_requests:
            return False, 0
        return True, max(1, int(recent[0] + window_seconds - now) + 1)

    def get_remaining(self, key: str, max_requests: int, window_seconds: int) -> int:
        cutoff = time.time() - window_seconds
        return max(0, max_requests - len([t for t in self._requests[key] if t > cutoff]))

    def reset(self) -> None:
        self._requests.clear()


rate_limiter = InMemoryRateLimiter()
_redis = None
_redis_failed_at = 0.0


def _get_redis():
    global _redis, _redis_failed_at
    if not settings.REDIS_URL or (_redis is None and time.time() - _redis_failed_at < 30):
        return None
    if _redis is None:
        try:
            import redis.asyncio as aioredis

            _redis = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
        except Exception as e:  # pragma: no cover
            log.warning("redis unavailable, using in-memory rate limiter: %s", e)
            _redis_failed_at = time.time()
            return None
    return _redis


async def _redis_window(r, key: str, max_requests: int, window_seconds: int, record: bool) -> tuple[bool, int]:
    """Sliding-window log in a Redis sorted set (scores = timestamps), so a burst cannot double the limit by
    straddling a window boundary (a fixed window would allow up to 2x). Returns (allowed, retry_after)."""
    now = time.time()
    zkey = f"rl:{key}"
    member = f"{now:.6f}:{secrets.token_hex(4)}"
    pipe = r.pipeline(transaction=True)
    pipe.zremrangebyscore(zkey, 0, now - window_seconds)
    if record:
        pipe.zadd(zkey, {member: now})
    pipe.zcard(zkey)
    pipe.expire(zkey, window_seconds + 1)
    results = await pipe.execute()
    count = int(results[2 if record else 1])
    over = count > max_requests if record else count >= max_requests
    if not over:
        return True, 0
    if record:
        await r.zrem(zkey, member)  # a rejected attempt must not extend the window
    oldest = await r.zrange(zkey, 0, 0, withscores=True)
    retry = max(1, int(oldest[0][1] + window_seconds - now) + 1) if oldest else window_seconds
    return False, retry


async def hit(key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
    """Count one request against ``key``. Returns (allowed, retry_after_seconds)."""
    if not settings.RATE_LIMIT_ENABLED:
        return True, 0
    r = _get_redis()
    if r is not None:
        global _redis, _redis_failed_at
        try:
            return await _redis_window(r, key, max_requests, window_seconds, record=True)
        except Exception as e:
            log.warning("redis rate limit failed, falling back to memory: %s", e)
            _redis, _redis_failed_at = None, time.time()
    return rate_limiter.check(key, max_requests, window_seconds)


async def peek(key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
    """Is `key` over its limit right now? Does not count the call (pair with `hit` when recording a failure).
    Returns (blocked, retry_after_seconds)."""
    if not settings.RATE_LIMIT_ENABLED:
        return False, 0
    r = _get_redis()
    if r is not None:
        global _redis, _redis_failed_at
        try:
            ok, retry = await _redis_window(r, key, max_requests, window_seconds, record=False)
            return (not ok), retry
        except Exception as e:
            log.warning("redis peek failed, falling back to memory: %s", e)
            _redis, _redis_failed_at = None, time.time()
    return rate_limiter.peek(key, max_requests, window_seconds)
