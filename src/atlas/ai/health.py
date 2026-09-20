"""Saude das rotas: circuit breaker, cooldown e metricas por rota.

Regra da missao: quando um provedor atinge o limite legitimo dele, ele vira
RATE_LIMITED e entra em cooldown; o router usa outro. Quando o cooldown acaba,
a rota volta em modo half-open (uma chamada de teste) e so retorna ao pool se
essa chamada passar. Nada aqui tenta contornar limite - so espera.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class Health(str, Enum):
    HEALTHY = "HEALTHY"
    COOLDOWN = "COOLDOWN"      # estourou limite ou falhou; volta sozinho
    DEAD = "DEAD"              # falhou repetidamente; precisa de reteste explicito


@dataclass
class RouteHealth:
    key: str
    state: Health = Health.HEALTHY
    consecutive_failures: int = 0
    total_success: int = 0
    total_failure: int = 0
    cooldown_until: float = 0.0
    cooldown_seconds: float = 30.0
    last_success: float | None = None
    last_error: str | None = None
    last_error_at: float | None = None
    latency_ema_ms: float | None = None
    #: quantas vezes a rota ja entrou em cooldown seguido; aumenta o tempo de espera
    trips: int = 0
    in_flight: int = 0
    extra: dict = field(default_factory=dict)

    def available(self, now: float) -> bool:
        if self.state is Health.DEAD:
            return False
        if self.state is Health.COOLDOWN and now < self.cooldown_until:
            return False
        return True


class HealthRegistry:
    """Estado de saude de todas as rotas do pool."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        dead_threshold: int = 12,
        base_cooldown: float = 30.0,
        max_cooldown: float = 900.0,
        concurrency_limit: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.dead_threshold = dead_threshold
        self.base_cooldown = base_cooldown
        self.max_cooldown = max_cooldown
        self.concurrency_limit = concurrency_limit
        self._clock = clock
        self._routes: dict[str, RouteHealth] = {}

    # ---------------------------------------------------------------- acesso
    def _now(self) -> float:
        return self._clock()

    def get(self, key: str) -> RouteHealth:
        if key not in self._routes:
            self._routes[key] = RouteHealth(key=key)
        return self._routes[key]

    def all(self) -> dict[str, RouteHealth]:
        return dict(self._routes)

    def is_available(self, key: str, *, now: float | None = None) -> bool:
        """Rota utilizavel agora? Inclui limite de concorrencia e half-open."""
        now = self._now() if now is None else now
        h = self.get(key)
        if h.in_flight >= self.concurrency_limit:
            return False
        return h.available(now)

    # -------------------------------------------------------------- ciclo de vida
    def begin(self, key: str) -> None:
        self.get(key).in_flight += 1

    def end(self, key: str) -> None:
        h = self.get(key)
        h.in_flight = max(0, h.in_flight - 1)

    def record_success(self, key: str, *, latency_ms: float | None = None) -> None:
        now = self._now()
        h = self.get(key)
        h.consecutive_failures = 0
        h.total_success += 1
        h.last_success = now
        h.last_error = None
        if latency_ms is not None:
            h.latency_ema_ms = (
                latency_ms if h.latency_ema_ms is None
                else 0.7 * h.latency_ema_ms + 0.3 * latency_ms
            )
        if h.state is not Health.DEAD:
            h.state = Health.HEALTHY
            h.trips = 0
            h.cooldown_seconds = self.base_cooldown

    def record_failure(
        self, key: str, *, reason: str, retryable: bool = True,
        rate_limited: bool = False,
    ) -> Health:
        """Registra falha e decide se a rota entra em cooldown ou morre.

        Falha nao-reintentavel (401, modelo inexistente) nao e fila: derruba a
        rota direto para DEAD, porque insistir nao vai resolver.

        rate_limited pula o failure_threshold de proposito. 429 nao e "talvez
        transitório": e o provedor dizendo "espera". Sem isso o router pagava a
        falha em TODA requisicao — e ficou pior depois que as irmas do gateway
        passaram a ser adiadas (uma rota so por pedido => nunca junta 3 falhas
        seguidas => cooldown nunca dispara => ~800ms jogados fora toda vez).
        """
        now = self._now()
        h = self.get(key)
        h.total_failure += 1
        h.consecutive_failures += 1
        h.last_error = reason
        h.last_error_at = now

        if not retryable:
            h.state = Health.DEAD
            return h.state

        if rate_limited or h.consecutive_failures >= self.failure_threshold:
            h.trips += 1
            h.consecutive_failures = 0
            # backoff exponencial: provedor que cai toda hora espera mais
            espera = min(self.base_cooldown * (2 ** (h.trips - 1)), self.max_cooldown)
            h.cooldown_seconds = espera
            h.cooldown_until = now + espera
            h.state = Health.DEAD if h.total_failure >= self.dead_threshold else Health.COOLDOWN
        return h.state

    def revive(self, key: str) -> None:
        """Reteste explicito: tira do DEAD e da uma chance em half-open."""
        h = self.get(key)
        h.state = Health.HEALTHY
        h.consecutive_failures = 0
        h.cooldown_until = 0.0
        h.trips = 0
        h.cooldown_seconds = self.base_cooldown

    # ------------------------------------------------------------------ painel
    def snapshot(self) -> dict[str, dict]:
        now = self._now()
        out: dict[str, dict] = {}
        for key, h in self._routes.items():
            # COOLDOWN que ja venceu vira HEALTHY na leitura, sem esperar chamada
            estado = h.state.value
            if h.state is Health.COOLDOWN and now >= h.cooldown_until:
                estado = "HALF_OPEN"
            out[key] = {
                "estado": estado,
                "sucessos": h.total_success,
                "falhas": h.total_failure,
                "falhas_seguidas": h.consecutive_failures,
                "latencia_ema_ms": round(h.latency_ema_ms, 1) if h.latency_ema_ms else None,
                "ultimo_erro": h.last_error,
                "cooldown_restante_s": max(0.0, round(h.cooldown_until - now, 1)),
                "em_voo": h.in_flight,
            }
        return out
