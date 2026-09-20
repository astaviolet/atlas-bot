"""Estado da tarefa (spec 22, 23, 89, 113).

Por que derivado e nao guardado: `AgentOutcome` tem 14 pontos de criacao no
agente. Acrescentar campo obrigatorio em todos seria ruido, e o estado ja esta
determinado pelos resultados + pelo motivo de bloqueio. Derivar garante que o
estado nunca diverge do que realmente aconteceu - guardar abria espaco para
alguem marcar COMPLETED sem ter executado, que e o "sucesso falso" da secao 185.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Sequence


class TaskState(str, Enum):
    """Estados da spec 89/113, reduzidos ao que este agente de fato distingue.

    QUEUED/PLANNING/EXECUTING/RECOVERING sao transitorios e nao sobrevivem ao
    retorno; ficam registrados no historico, nao no resultado final.
    """

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    NOTHING_TO_DO = "nothing_to_do"


#: blocked -> estado. Tudo que nao esta aqui e tratado pelos resultados.
_POR_BLOQUEIO = {
    "confirmation_required": TaskState.AWAITING_CONFIRMATION,
    "awaiting_confirmation": TaskState.AWAITING_CONFIRMATION,
    "confirmation_expired": TaskState.CANCELLED,
    "guild_busy": TaskState.REJECTED,
    "prompt_injection": TaskState.REJECTED,
    "policy_denied": TaskState.REJECTED,
    "forbidden": TaskState.REJECTED,
}


def estado_da_tarefa(results: Sequence[Any], blocked: str | None = None) -> TaskState:
    """Classifica o resultado final. Nunca levanta."""
    if blocked:
        estado = _POR_BLOQUEIO.get(blocked)
        if estado is not None:
            return estado

    feitos = [r for r in results if getattr(r, "ok", False)]
    falhas = [r for r in results if not getattr(r, "ok", True)]

    if feitos and falhas:
        return TaskState.PARTIAL
    if falhas:
        return TaskState.FAILED
    if feitos:
        return TaskState.COMPLETED
    return TaskState.NOTHING_TO_DO


def resumo_da_tarefa(results: Sequence[Any]) -> str:
    """Linha curta de fechamento (spec 22/157): o que fez, o que nao fez.

    Sem isto o usuario recebe uma lista e tem que contar. Com falha parcial a
    conta importa: "16 de 18" nao e "tudo pronto".
    """
    feitos = sum(1 for r in results if getattr(r, "ok", False))
    falhas = sum(1 for r in results if not getattr(r, "ok", True))
    if falhas == 0:
        return f"{feitos} concluida(s)"
    if feitos == 0:
        return f"nenhuma concluida, {falhas} falha(s)"
    return f"{feitos} concluida(s), {falhas} falha(s) - nao foi tudo"
