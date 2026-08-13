"""Replaceable abuse-control boundary for API request limits."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class RateLimiter(Protocol):
    async def consume(
        self, *, key: str, limit: int, window_seconds: int
    ) -> RateLimitDecision: ...


class RedisLikeClient(Protocol):
    async def eval(
        self, script: str, numkeys: int, *keys_and_arguments: str
    ) -> object: ...


class RateLimitUnavailable(RuntimeError):
    """The configured shared rate-limit store cannot be reached."""


class RateLimitExceeded(PermissionError):
    """A request exceeded a configured policy."""

    def __init__(self, decision: RateLimitDecision) -> None:
        super().__init__("Request rate limit exceeded")
        self.decision = decision


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    identity_limit: int
    ip_limit: int
    device_limit: int | None
    window_seconds: int


DEFAULT_RATE_LIMIT_POLICIES: dict[str, RateLimitPolicy] = {
    "ai": RateLimitPolicy(identity_limit=60, ip_limit=200, device_limit=120, window_seconds=3600),
    "voice": RateLimitPolicy(identity_limit=20, ip_limit=80, device_limit=40, window_seconds=3600),
    "evidence": RateLimitPolicy(identity_limit=40, ip_limit=160, device_limit=80, window_seconds=3600),
    "complaint": RateLimitPolicy(identity_limit=10, ip_limit=40, device_limit=20, window_seconds=3600),
    "identity": RateLimitPolicy(identity_limit=10, ip_limit=30, device_limit=20, window_seconds=3600),
    "public": RateLimitPolicy(identity_limit=0, ip_limit=120, device_limit=None, window_seconds=3600),
    "operator": RateLimitPolicy(identity_limit=300, ip_limit=600, device_limit=None, window_seconds=3600),
}

# This is a conservative fixed window used for launch controls. It is a
# request cap, not a currency budget; provider spend alerts remain required.
MONTHLY_BUDGET_WINDOW_SECONDS = 31 * 24 * 60 * 60


class NoopRateLimiter(RateLimiter):
    """Explicit non-production fallback; production construction rejects it."""

    async def consume(
        self, *, key: str, limit: int, window_seconds: int
    ) -> RateLimitDecision:
        del key, window_seconds
        return RateLimitDecision(
            allowed=True,
            limit=limit,
            remaining=limit,
            retry_after_seconds=0,
        )


class InMemoryRateLimiter(RateLimiter):
    """Deterministic fixture; not suitable for multiple production instances."""

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, int]] = {}
        self._lock = asyncio.Lock()

    async def consume(
        self, *, key: str, limit: int, window_seconds: int
    ) -> RateLimitDecision:
        now = time.monotonic()
        async with self._lock:
            started, count = self._buckets.get(key, (now, 0))
            if now - started >= window_seconds:
                started, count = now, 0
            count += 1
            self._buckets[key] = (started, count)
            remaining = max(limit - count, 0)
            retry_after = max(int(window_seconds - (now - started)), 1)
            return RateLimitDecision(
                allowed=count <= limit,
                limit=limit,
                remaining=remaining,
                retry_after_seconds=retry_after if count > limit else 0,
            )


_REDIS_COUNTER_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""


class RedisRateLimiter(RateLimiter):
    """Atomic fixed-window limiter over any Redis-compatible async client."""

    def __init__(self, client: RedisLikeClient, *, key_prefix: str = "aineta:rl:") -> None:
        self._client = client
        self._key_prefix = key_prefix

    async def consume(
        self, *, key: str, limit: int, window_seconds: int
    ) -> RateLimitDecision:
        try:
            raw = await self._client.eval(
                _REDIS_COUNTER_SCRIPT,
                1,
                f"{self._key_prefix}{key}",
                str(limit),
                str(window_seconds),
            )
        except Exception as exc:
            raise RateLimitUnavailable("Shared rate-limit store is unavailable") from exc
        try:
            count = int(raw[0])  # type: ignore[index]
            ttl = int(raw[1])  # type: ignore[index]
        except (IndexError, TypeError, ValueError) as exc:
            raise RateLimitUnavailable("Shared rate-limit store returned an invalid result") from exc
        return RateLimitDecision(
            allowed=count <= limit,
            limit=limit,
            remaining=max(limit - count, 0),
            retry_after_seconds=max(ttl, 1) if count > limit else 0,
        )


def hashed_limit_key(*, policy: str, dimension: str, value: str) -> str:
    """Keep identity, IP, and device values out of the shared store key."""

    material = f"aineta:{policy}:{dimension}:{value}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


async def consume_global_budget(
    limiter: RateLimiter,
    *,
    budget_name: str,
    limit: int,
    window_seconds: int = MONTHLY_BUDGET_WINDOW_SECONDS,
) -> RateLimitDecision:
    """Consume a shared request budget without tying it to a citizen.

    The key is deliberately global and hashed. This keeps a fleet-wide cap
    effective when the production adapter is Redis-compatible, while the same
    interface remains deterministic for local tests.
    """

    if limit < 1:
        raise ValueError("Global budget limit must be positive")
    if window_seconds < 1:
        raise ValueError("Global budget window must be positive")
    return await limiter.consume(
        key=hashed_limit_key(policy=budget_name, dimension="global", value="all"),
        limit=limit,
        window_seconds=window_seconds,
    )
