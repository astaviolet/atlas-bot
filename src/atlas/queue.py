"""Fila de acoes. Todo efeito no Discord passa por aqui, sem excecao.

    LLM -> ActionQueue -> RateLimiter -> Policy/Permissions -> DiscordGateway

O modelo nunca chama o Discord direto.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from .audit import AuditLog
from .config import Limits
from .autofix import corrigir, diferenca
from .errors import AtlasError
from .policy import DESTRUCTIVE_TOOLS
from .ratelimit import GuildRateLimiter

log = logging.getLogger(__name__)


@dataclass
class PlannedAction:
    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    label: str = ""
    # id da tool call que originou esta acao; volta para o modelo junto do resultado
    call_id: str | None = None

    def describe(self) -> str:
        return self.label or self.tool


@dataclass
class ActionResult:
    action: PlannedAction
    ok: bool
    data: Any = None
    error: str | None = None
    error_kind: str | None = None
    verified: bool | None = None
    user_message: str | None = None

    def summary_line(self) -> str:
        mark = "✅" if self.ok else "❌"
        base = f"{mark} {self.action.describe()}"
        if not self.ok and self.error:
            base += f" — {self.error}"
        elif self.verified:
            base += " — confirmado"
        return base


ToolHandler = Callable[[PlannedAction], Any]


class ActionQueue:
    """Executa acoes em serie, com rate limit e auditoria.

    `dispatch` e injetado pelo Executor, que e quem de fato valida e chama o gateway.
    """

    def __init__(
        self,
        *,
        guild_id: int,
        limiter: GuildRateLimiter,
        audit: AuditLog,
        dispatch: ToolHandler,
        limits: Limits | None = None,
    ) -> None:
        self.guild_id = guild_id
        self.limiter = limiter
        self.audit = audit
        self.dispatch = dispatch
        # Limites de nome/topico para a auto-correcao cortar no tamanho certo.
        self.limits = limits or Limits()
        self._pending: list[PlannedAction] = []
        self._executed: list[ActionResult] = []

    @property
    def pending(self) -> list[PlannedAction]:
        return list(self._pending)

    @property
    def executed(self) -> list[ActionResult]:
        return list(self._executed)

    def submit(self, action: PlannedAction) -> None:
        self._pending.append(action)

    def submit_many(self, actions: list[PlannedAction]) -> None:
        self._pending.extend(actions)

    def clear_pending(self) -> None:
        self._pending.clear()

    def run_one(self, action: PlannedAction, *, corrigiu: bool = False) -> ActionResult:
        """Executa uma acao isolada. Nunca levanta: devolve ActionResult."""
        self.limiter.acquire(self.guild_id, action=action.tool)
        try:
            data = self.dispatch(action)
        except AtlasError as exc:
            log.warning("acao %s falhou: %s", action.tool, exc)
            result = ActionResult(
                action=action,
                ok=False,
                error=str(exc),
                error_kind=type(exc).__name__,
                user_message=getattr(exc, "user_message", None),
            )
        except Exception as exc:  # noqa: BLE001 - fronteira externa
            log.exception("erro inesperado em %s", action.tool)
            result = ActionResult(
                action=action,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                error_kind=type(exc).__name__,
                user_message="Algo inesperado aconteceu nessa operacao.",
            )
        else:
            verified = data.get("verified") if isinstance(data, dict) else None
            result = ActionResult(action=action, ok=True, data=data, verified=verified)

        # Auto-correcao (spec 25): se o erro tem conserto conhecido, corrige e
        # tenta UMA vez. Sem laco - retry infinito aqui seria um jeito de travar
        # a run. E sem inventar: corrigir() devolve None quando o unico valor
        # possivel seria adivinhado.
        if not result.ok and not corrigiu:
            novo_params = corrigir(
                result.error or "", action.params,
                max_name_len=self.limits.max_name_len,
                max_topic_len=self.limits.max_topic_len,
            )
            if novo_params is not None:
                self.audit.record(
                    action="autofix.retry",
                    guild_id=self.guild_id,
                    params={"tool": action.tool, "motivo": result.error,
                            "mudanca": diferenca(action.params, novo_params)},
                    result="ok",
                )
                log.info("autofix %s (%s): %s", action.tool, result.error,
                         diferenca(action.params, novo_params))
                corrigida = replace(
                    action,
                    params=novo_params,
                    label=f"{action.describe()} (corrigido)",
                )
                return self.run_one(corrigida, corrigiu=True)

        self.audit.record(
            action=action.tool,
            guild_id=self.guild_id,
            params=action.params,
            result="ok" if result.ok else "error",
            error=result.error,
            extra={"verified": result.verified} if result.verified is not None else None,
        )
        self._executed.append(result)
        return result

    def run_all(self) -> list[ActionResult]:
        results: list[ActionResult] = []
        while self._pending:
            action = self._pending.pop(0)
            results.append(self.run_one(action))
        return results

    @staticmethod
    def partition(actions: list[PlannedAction]) -> dict[str, int]:
        """Contagem para checagem de cota."""
        creates = sum(1 for a in actions if a.tool.startswith("create_"))
        deletes = sum(1 for a in actions if a.tool in DESTRUCTIVE_TOOLS)
        return {"actions": len(actions), "creates": creates, "deletes": deletes}
