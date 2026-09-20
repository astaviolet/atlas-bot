"""Estados do agente (spec 113) e prioridade de tarefa (spec 115).

POR QUE OS DOIS MORAM JUNTOS
----------------------------
Os dois respondem à mesma pergunta em momentos diferentes: "o que o agente está
fazendo agora, e isso pode esperar?". Estado diz o que está acontecendo;
prioridade diz quem tem vez quando dois querem a mesma coisa.

ESTADO (113) — RASTREADO, NÃO DECLARADO
---------------------------------------
O estado é registrado a cada transição e devolvido no resultado final. Ele é
derivado do que o agente de fato fez, então não tem como marcar COMPLETED sem
ter executado — que é o sucesso falso que a spec 185 proíbe.

PRIORIDADE (115) — O QUE ELA MUDA DE VERDADE
--------------------------------------------
Não é um número decorativo. Ela muda a escolha de rota: um pedido do usuário
pode usar uma rota degradada (responder devagar é melhor que não responder),
enquanto descoberta em segundo plano só usa rota saudável — sondar provider com
rota já ruim é gastar cota gratuita à toa e ainda piorar a saúde medida.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any


class AgentState(str, Enum):
    """Estados da spec 113.

    IDLE e UNDERSTANDING existem, mas não sobrevivem ao retorno: ficam no
    histórico de transições, não no resultado.
    """

    IDLE = "idle"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    WAITING_CONFIRMATION = "waiting_confirmation"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"


#: transições aceitas. Não é burocracia: pular de PLANNING para COMPLETED sem
#: passar por EXECUTING é exatamente o "disse que fez sem fazer" da spec 185.
_TRANSICOES: dict[AgentState, frozenset[AgentState]] = {
    AgentState.IDLE: frozenset({AgentState.UNDERSTANDING}),
    AgentState.UNDERSTANDING: frozenset({AgentState.PLANNING, AgentState.FAILED}),
    AgentState.PLANNING: frozenset({
        AgentState.WAITING_CONFIRMATION, AgentState.EXECUTING, AgentState.FAILED,
        # COMPLETED a partir de PLANNING e legitimo: o plano pode nao exigir
        # acao nenhuma (pedido de leitura, ou tudo ja existia pela Fase 3).
        AgentState.COMPLETED,
    }),
    AgentState.WAITING_CONFIRMATION: frozenset({
        AgentState.EXECUTING, AgentState.IDLE, AgentState.FAILED,
    }),
    AgentState.EXECUTING: frozenset({
        AgentState.VERIFYING, AgentState.RECOVERING, AgentState.PLANNING,
        AgentState.COMPLETED, AgentState.FAILED,
    }),
    AgentState.VERIFYING: frozenset({
        AgentState.RECOVERING, AgentState.COMPLETED, AgentState.PLANNING,
        AgentState.FAILED,
    }),
    AgentState.RECOVERING: frozenset({
        AgentState.EXECUTING, AgentState.COMPLETED, AgentState.FAILED,
    }),
    AgentState.COMPLETED: frozenset({AgentState.IDLE}),
    AgentState.FAILED: frozenset({AgentState.IDLE}),
}


class RastreadorDeEstado:
    """Guarda o estado atual e o histórico de transições. Nunca levanta."""

    def __init__(self, clock: Any = time.monotonic) -> None:
        self._estado = AgentState.IDLE
        self._historico: list[tuple[str, float]] = [(AgentState.IDLE.value, clock())]
        self._clock = clock
        self._invalidas: list[str] = []

    @property
    def estado(self) -> AgentState:
        return self._estado

    @property
    def historico(self) -> list[tuple[str, float]]:
        return list(self._historico)

    @property
    def transicoes_invalidas(self) -> list[str]:
        """Ficam registradas em vez de explodir: um estado errado é dado de
        diagnóstico, não motivo para derrubar o pedido do usuário."""
        return list(self._invalidas)

    def ir_para(self, novo: AgentState) -> bool:
        if novo == self._estado:
            return True
        if novo not in _TRANSICOES.get(self._estado, frozenset()):
            self._invalidas.append(f"{self._estado.value} -> {novo.value}")
            return False
        self._estado = novo
        self._historico.append((novo.value, self._clock()))
        return True

    def reiniciar(self) -> None:
        self._estado = AgentState.IDLE
        self._historico = [(AgentState.IDLE.value, self._clock())]
        self._invalidas.clear()


class Prioridade(str, Enum):
    """Spec 115. Menor número = mais urgente."""

    SECURITY = "security"
    SYSTEM = "system"
    USER_ACTION = "user_action"
    BACKGROUND = "background"
    DISCOVERY = "discovery"


_ORDEM = {
    Prioridade.SECURITY: 0,
    Prioridade.SYSTEM: 1,
    Prioridade.USER_ACTION: 2,
    Prioridade.BACKGROUND: 3,
    Prioridade.DISCOVERY: 4,
}

#: Até que nível de saúde cada prioridade aceita usar.
#: USER_ACTION tolera DEGRADED: responder devagar vale mais que não responder
#: (spec 59: não dizer "não consigo" enquanto houver alternativa).
#: DISCOVERY exige HEALTHY: sondar com rota ruim queima cota gratuita e ainda
#: piora a saúde medida da rota.
_TOLERANCIA = {
    Prioridade.SECURITY: 2,
    Prioridade.SYSTEM: 2,
    Prioridade.USER_ACTION: 2,
    Prioridade.BACKGROUND: 1,
    Prioridade.DISCOVERY: 0,
}


def mais_urgente(a: Prioridade, b: Prioridade) -> Prioridade:
    return a if _ORDEM[a] <= _ORDEM[b] else b


def aceita_saude(prioridade: Prioridade, nivel: int) -> bool:
    """`nivel`: 0 = saudável, 1 = degradada, 2 = qualquer uma que responda."""
    return nivel <= _TOLERANCIA[prioridade]


def tolerancia(prioridade: Prioridade) -> int:
    return _TOLERANCIA[prioridade]
