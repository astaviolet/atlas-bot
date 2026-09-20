"""Descoberta e reavaliacao continua do pool.

O catalogo em `providers.py` e uma foto: provedor gratuito muda de modelo, de
limite e de disponibilidade sem avisar. Este modulo re-testa as rotas de
verdade e devolve o estado atual, para o pool nao ficar carregando rota morta.

Reavaliacao:
    rota nova   -> probe -> classifica -> entra no pool se passar
    rota quebrada -> probe falha -> cooldown -> reteste depois -> volta se passar

O probe e deliberadamente minimo (prompt curto, poucos tokens, uma chamada por
rota, serial e com pausa). Nao bombardeia endpoint de ninguem.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from ..errors import AIError
from .health import HealthRegistry
from .openai_client import OpenAICompatibleClient, classify_error
from .providers import Gateway, ModelRoute

log = logging.getLogger(__name__)

# O prompt precisa EXIGIR a ferramenta. Um probe que diz "responda apenas: ok"
# faz o modelo obedecer e responder texto - e a rota boa seria descartada como
# "sem tool calling". Esse falso negativo custou uma rodada inteira de teste.
PROMPT_PROBE = "Chame a ferramenta ping passando v igual a 1. Nao responda em texto."
# Formato interno de declaracao (o mesmo do ToolRegistry). A conversao para o
# envelope OpenAI acontece dentro do cliente, via to_openai_tools.
TOOL_PROBE = [
    {
        "name": "ping",
        "description": "Ferramenta de teste",
        "parameters": {"type": "object", "properties": {"v": {"type": "string"}}, "required": ["v"]},
    }
]


class ProbeStatus:
    OK = "OK"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    NOT_FOUND = "NOT_FOUND"
    NO_TOOL_CALLING = "NO_TOOL_CALLING"
    SERVER_ERROR = "SERVER_ERROR"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


@dataclass
class ProbeResult:
    route: str
    status: str
    ok: bool
    tool_calling: bool = False
    latency_ms: float | None = None
    detail: str = ""

    @property
    def utilizavel(self) -> bool:
        return self.status == ProbeStatus.OK and self.tool_calling


def _status_from(exc: AIError) -> str:
    tipo = classify_error(exc)
    return {
        "rate_limit": ProbeStatus.RATE_LIMITED,
        "auth": ProbeStatus.AUTH_REQUIRED,
        "not_found": ProbeStatus.NOT_FOUND,
        "timeout": ProbeStatus.TIMEOUT,
        "server_error": ProbeStatus.SERVER_ERROR,
        "connection": ProbeStatus.SERVER_ERROR,
    }.get(tipo, ProbeStatus.ERROR)


def probe_rota(
    gateway: Gateway,
    rota: ModelRoute,
    *,
    client: Any | None = None,
    testar_tool: bool = True,
) -> ProbeResult:
    """Uma chamada minima na rota. Devolve o que aconteceu, sem levantar."""
    cliente = client or OpenAICompatibleClient(
        api_key=gateway.api_key,
        base_url=gateway.base_url,
        model_name=rota.model,
        timeout=30.0,
        max_retries=0,
    )
    inicio = time.perf_counter()
    try:
        turno = cliente.generate(
            system="Voce responde de forma minima.",
            history=[{"role": "user", "parts": [{"text": PROMPT_PROBE}]}],
            tools=TOOL_PROBE if testar_tool else [],
            model=rota.model,
        )
    except AIError as exc:
        return ProbeResult(
            route=rota.key,
            status=_status_from(exc),
            ok=False,
            latency_ms=round((time.perf_counter() - inicio) * 1000, 1),
            detail=(exc.user_message or str(exc))[:140],
        )
    except Exception as exc:  # noqa: BLE001 - fronteira externa
        return ProbeResult(
            route=rota.key, status=ProbeStatus.ERROR, ok=False,
            detail=f"{type(exc).__name__}: {exc}"[:140],
        )

    latencia = round((time.perf_counter() - inicio) * 1000, 1)
    tem_tool = bool(turno.calls)
    if testar_tool and not tem_tool:
        return ProbeResult(
            route=rota.key, status=ProbeStatus.NO_TOOL_CALLING, ok=False,
            tool_calling=False, latency_ms=latencia,
            detail="respondeu, mas nao emitiu tool call",
        )
    return ProbeResult(
        route=rota.key, status=ProbeStatus.OK, ok=True,
        tool_calling=tem_tool, latency_ms=latencia,
    )


def reavaliar(
    catalog: Iterable[Gateway],
    *,
    health: HealthRegistry | None = None,
    pausa: float = 1.0,
    sleeper: Callable[[float], None] = time.sleep,
    on_result: Callable[[ProbeResult], None] | None = None,
    client_factory: Callable[[Gateway, ModelRoute], Any] | None = None,
) -> tuple[HealthRegistry, list[ProbeResult]]:
    """Retesta o catalogo inteiro e atualiza o registro de saude.

    Rota que passa volta ao pool (`revive`). Rota que falha entra em cooldown
    ou morre conforme o motivo: credencial/modelo inexistente e permanente,
    fila e temporario.
    """
    reg = health or HealthRegistry()
    resultados: list[ProbeResult] = []

    rotas = [(g, m) for g in catalog for m in g.models]
    for i, (gateway, rota) in enumerate(rotas):
        cliente = client_factory(gateway, rota) if client_factory else None
        r = probe_rota(gateway, rota, client=cliente)
        resultados.append(r)
        if on_result:
            on_result(r)

        if r.utilizavel:
            reg.revive(rota.key)
            reg.record_success(rota.key, latency_ms=r.latency_ms)
        else:
            permanente = r.status in (
                ProbeStatus.AUTH_REQUIRED,
                ProbeStatus.NOT_FOUND,
                ProbeStatus.NO_TOOL_CALLING,
            )
            # NO_TOOL_CALLING e permanente para este agente: sem tool calling a
            # rota nao serve, e insistir nao muda isso.
            reg.record_failure(rota.key, reason=f"{r.status}: {r.detail}", retryable=not permanente)

        if i < len(rotas) - 1 and pausa:
            sleeper(pausa)

    return reg, resultados


def resumo_probes(resultados: list[ProbeResult]) -> dict[str, Any]:
    """Contagem por status, para painel e log."""
    contagem: dict[str, int] = {}
    for r in resultados:
        contagem[r.status] = contagem.get(r.status, 0) + 1
    return {
        "testadas": len(resultados),
        "utilizaveis": sum(1 for r in resultados if r.utilizavel),
        "por_status": contagem,
        "rotas_ok": [r.route for r in resultados if r.utilizavel],
    }
