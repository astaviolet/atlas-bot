"""Roteador do pool de IA.

Implementa o mesmo Protocol que o resto do bot ja conhece (ModelClient), entao
agente, executor e testes continuam iguais: eles pedem um turno e recebem um
turno. Quem decide gateway, modelo, retry e fallback e so este modulo.

Ordem de decisao a cada pedido:

    1. capability routing  - so rotas que sabem fazer o que o pedido exige
                             (tool calling e eliminatorio para este agente)
    2. saude               - circuit breaker: rota em cooldown ou morta nao entra
    3. limite do provedor  - balde de tokens por gateway, no limite legitimo dele
    4. carga               - round robin ponderado: nao empilha tudo na primeira
    5. latencia            - desempate por tempo de resposta medido
    6. falhou?             - registra, marca cooldown se for o caso, tenta a proxima

Nada aqui tenta contornar rate limit. Quando o provedor diz 429/503, a rota
espera o cooldown e outro provedor assume.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from ..errors import AIError
from ..ratelimit import TokenBucket
from .base import ModelTurn
from .cache import RequestCache, chave_pedido
from .health import HealthRegistry
from .openai_client import OpenAICompatibleClient, classify_error
from .providers import CATALOG, Capabilities, Gateway, ModelRoute
from .stats import PoolStats

log = logging.getLogger(__name__)


class Router:
    """ModelClient que distribui a carga entre varias rotas anonimas."""

    def __init__(
        self,
        catalog: list[Gateway] | None = None,
        *,
        client_factory: Callable[[Gateway], Any] | None = None,
        health: HealthRegistry | None = None,
        stats: PoolStats | None = None,
        cache: RequestCache | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_attempts: int = 8,
        #: Dormir entre trocas de rota custava ate 10s por troca. Com 12 rotas
        #: no pool a troca tem que ser quase instantanea: a proxima rota esta
        #: pronta, nao ha o que esperar.
        backoff_seconds: float = 0.4,
        use_cache: bool = True,
    ) -> None:
        self.catalog: list[Gateway] = catalog if catalog is not None else list(CATALOG)
        self._factory = client_factory or self._default_factory
        self.health = health or HealthRegistry(clock=clock)
        self.stats = stats or PoolStats()
        self.cache = cache if cache is not None else RequestCache(clock=clock)
        self.use_cache = use_cache
        self._clock = clock
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds

        self._clients: dict[str, Any] = {}
        self._buckets: dict[str, TokenBucket] = {}
        self._servidos: dict[str, int] = {}
        self._lock = threading.Lock()

        #: exposto para diagnostico: qual rota respondeu por ultimo
        self.last_route: str | None = None
        #: quantas rotas o catalogo conhece (para painel)
        self.total_routes = sum(len(g.models) for g in self.catalog)

    # ------------------------------------------------------------- infraestrutura
    @staticmethod
    def _default_factory(gateway: Gateway) -> Any:
        """Um cliente HTTP por gateway, reutilizado entre as rotas dele.

        O modelo e passado por chamada, entao aqui basta um nome qualquer valido
        para satisfazer o construtor; quem decide o modelo e o Router.
        """
        return OpenAICompatibleClient(
            api_key=gateway.api_key,
            base_url=gateway.base_url,
            model_name=gateway.models[0].model if gateway.models else "indefinido",
            timeout=90.0,
            max_retries=0,  # retry e responsabilidade do Router, nao do SDK
        )

    def client_for(self, gateway: Gateway) -> Any:
        with self._lock:
            if gateway.id not in self._clients:
                self._clients[gateway.id] = self._factory(gateway)
            return self._clients[gateway.id]

    def bucket_for(self, gateway: Gateway) -> TokenBucket | None:
        """Balde no limite legitimo declarado pelo provedor. None = sem limite conhecido."""
        if not gateway.rpm:
            return None
        with self._lock:
            if gateway.id not in self._buckets:
                self._buckets[gateway.id] = TokenBucket(
                    capacity=max(1, gateway.rpm),
                    refill_per_sec=gateway.rpm / 60.0,
                    clock=self._clock,
                )
            return self._buckets[gateway.id]

    def _gateway_of(self, route: ModelRoute) -> Gateway | None:
        for g in self.catalog:
            if g.id == route.gateway:
                return g
        return None

    # ------------------------------------------------------------ selecao de rota
    def candidatos(self, needed: Capabilities) -> list[ModelRoute]:
        """Rotas que atendem a capacidade pedida, independente de saude."""
        return [
            m for g in self.catalog for m in g.models if m.caps.satisfies(needed)
        ]

    def escolher(self, needed: Capabilities, *, now: float | None = None) -> ModelRoute | None:
        """Melhor rota utilizavel agora, ou None se o pool inteiro estiver indisponivel."""
        now = self._clock() if now is None else now
        melhor: ModelRoute | None = None
        melhor_score: tuple | None = None

        for rota in self.candidatos(needed):
            if not self.health.is_available(rota.key, now=now):
                continue
            balde = self.bucket_for(self._gateway_of(rota) or Gateway(id=rota.gateway, base_url=""))
            if balde is not None and balde.available < 1.0:
                continue  # limite legitimo do provedor atingido: nao insiste

            h = self.health.get(rota.key)
            servidos = self._servidos.get(rota.key, 0)
            carga = servidos / max(1, rota.weight)          # round robin ponderado
            latencia = h.latency_ema_ms if h.latency_ema_ms is not None else 0.0
            score = (h.consecutive_failures, round(carga, 6), latencia)
            if melhor_score is None or score < melhor_score:
                melhor, melhor_score = rota, score
        return melhor

    # --------------------------------------------------------------------- chamada
    def generate(
        self,
        *,
        system: str,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        guild_id: int | None = None,
    ) -> ModelTurn:
        needed = Capabilities(tool_calling=bool(tools))
        if not self.candidatos(needed):
            raise AIError(
                "nenhuma rota no catalogo atende o que o pedido exige",
                user_message=(
                    "Nenhum modelo disponivel sabe fazer o que esse pedido precisa. "
                    "Nao adianta tentar de novo agora."
                ),
            )

        cache_key = None
        if self.use_cache and guild_id is not None:
            cache_key = chave_pedido(
                guild_id=guild_id, system=system, history=history, tools=tools
            )
            guardado = self.cache.get(guild_id, cache_key)
            if guardado is not None:
                self.stats.cache_hit()
                log.info("cache: reutilizando resposta para guild %s", guild_id)
                return guardado

        self.stats.request()
        tentadas: list[str] = []
        ultimo_erro: AIError | None = None
        now = self._clock()

        for tentativa in range(self.max_attempts):
            rota = self.escolher(needed, now=now)
            if rota is None:
                break
            if rota.key in tentadas:
                # ja falhou neste pedido; nao repete a mesma rota em loop
                break
            tentadas.append(rota.key)
            if tentativa > 0:
                self.stats.fallback()

            gateway = self._gateway_of(rota)
            balde = self.bucket_for(gateway) if gateway else None
            if balde is not None:
                balde.try_acquire(1.0)

            self.health.begin(rota.key)
            inicio = time.perf_counter()
            try:
                client = self.client_for(gateway) if gateway else None
                if client is None:
                    raise AIError(f"gateway {rota.gateway} nao esta no catalogo")
                turno = client.generate(
                    system=system,
                    history=history,
                    tools=tools,
                    model=rota.model,
                )
            except AIError as exc:
                self.health.end(rota.key)
                latencia = (time.perf_counter() - inicio) * 1000
                reintentavel = exc.retryable
                self.health.record_failure(
                    rota.key, reason=exc.user_message or str(exc), retryable=reintentavel
                )
                self.stats.failure(rota.key, kind=classify_error(exc))
                ultimo_erro = exc
                log.warning(
                    "rota %s falhou (%s, %dms); procurando outra",
                    rota.key, type(exc).__name__, latencia,
                )
                if reintentavel:
                    time.sleep(min(self.backoff_seconds * (tentativa + 1), 1.5))
                now = self._clock()
                continue
            except Exception as exc:  # noqa: BLE001 - fronteira externa
                self.health.end(rota.key)
                self.health.record_failure(rota.key, reason=type(exc).__name__, retryable=True)
                self.stats.failure(rota.key, kind="unexpected")
                ultimo_erro = AIError(str(exc), user_message="O provedor de IA falhou.")
                now = self._clock()
                continue

            self.health.end(rota.key)
            latencia = (time.perf_counter() - inicio) * 1000
            self.health.record_success(rota.key, latency_ms=latencia)
            self.stats.success(rota.key, latency_ms=latencia)
            with self._lock:
                self._servidos[rota.key] = self._servidos.get(rota.key, 0) + 1
            self.last_route = rota.key
            log.info("rota %s respondeu em %dms", rota.key, latencia)

            if cache_key is not None and guild_id is not None:
                self.cache.put(guild_id, cache_key, turno)
            return turno

        raise AIError(
            "todas as rotas disponiveis falharam" + (f" (tentadas: {', '.join(tentadas)})" if tentadas else ""),
            user_message=(
                "Nenhum provedor de IA respondeu agora. Eles sao gratuitos e as vezes "
                "ficam sobrecarregados - tenta de novo em alguns instantes."
            ),
        ) from ultimo_erro

    # ------------------------------------------------------------------ mutacao
    def invalidar_guild(self, guild_id: int) -> None:
        """Depois de mudar o servidor, resposta antiga nao serve mais."""
        self.cache.invalidate_guild(guild_id)

    # -------------------------------------------------------------------- painel
    def snapshot(self) -> dict[str, Any]:
        estados = [h["estado"] for h in self.health.snapshot().values()]
        return {
            "rotas_no_catalogo": self.total_routes,
            "rotas_usadas": len(self.health.all()),
            "saudaveis": estados.count("HEALTHY") + estados.count("HALF_OPEN"),
            "em_cooldown": estados.count("COOLDOWN"),
            "mortas": estados.count("DEAD"),
            "ultima_rota": self.last_route,
            "cache": self.cache.stats(),
            **self.stats.snapshot(),
        }
