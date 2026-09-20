"""Rate limiter. Balde de tokens por servidor + contadores por plano."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .errors import RateLimited


class TokenBucket:
    """Balde classico. `refill_per_sec` tokens por segundo, ate `capacity`."""

    def __init__(self, capacity: int, refill_per_sec: float, *, clock=time.monotonic) -> None:
        if capacity <= 0:
            raise ValueError("capacity precisa ser > 0")
        self.capacity = float(capacity)
        self.refill_per_sec = float(refill_per_sec)
        self._clock = clock
        self._tokens = float(capacity)
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_sec)
        self._last = now

    @property
    def available(self) -> float:
        self._refill()
        return self._tokens

    def try_acquire(self, cost: float = 1.0) -> bool:
        self._refill()
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False

    def wait_seconds(self, cost: float = 1.0) -> float:
        self._refill()
        deficit = cost - self._tokens
        if deficit <= 0:
            return 0.0
        return deficit / self.refill_per_sec


@dataclass
class PlanCounter:
    """Quanto um plano ja gastou."""

    actions: int = 0
    creates: int = 0
    deletes: int = 0
    destructive: int = 0
    history: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.actions = 0
        self.creates = 0
        self.deletes = 0
        self.destructive = 0
        self.history.clear()


class GuildRateLimiter:
    """Um balde por servidor. Impede rajada instantanea de chamadas."""

    def __init__(
        self,
        capacity: int,
        refill_per_sec: float,
        *,
        max_wait_seconds: float = 10.0,
        clock=time.monotonic,
        sleeper=time.sleep,
    ) -> None:
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self.max_wait_seconds = max_wait_seconds
        self._clock = clock
        self._sleeper = sleeper
        self._buckets: dict[int, TokenBucket] = {}

    def bucket(self, guild_id: int) -> TokenBucket:
        bucket = self._buckets.get(guild_id)
        if bucket is None:
            bucket = TokenBucket(self.capacity, self.refill_per_sec, clock=self._clock)
            self._buckets[guild_id] = bucket
        return bucket

    def acquire(self, guild_id: int, cost: float = 1.0, *, action: str = "") -> None:
        bucket = self.bucket(guild_id)
        if bucket.try_acquire(cost):
            return
        wait = bucket.wait_seconds(cost)
        if wait > self.max_wait_seconds:
            raise RateLimited(
                f"rate limit: esperaria {wait:.1f}s por {action or 'acao'}",
                user_message=(
                    "Chegamos no limite de velocidade da API. "
                    "Pedi pausas maiores do que e razoavel aqui — vamos continuar em outro momento."
                ),
            )
        self._sleeper(wait)
        if not bucket.try_acquire(cost):  # pragma: no cover - race defensivo
            raise RateLimited(f"rate limit persiste para {action or 'acao'}")

    def reset(self, guild_id: int) -> None:
        self._buckets.pop(guild_id, None)
