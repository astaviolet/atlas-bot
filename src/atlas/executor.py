"""Executor. Camada que fica entre o modelo e o Discord.

Ordem de validacao para CADA chamada, sempre nesta ordem:
    1. ferramenta existe e e permitida (policy)
    2. chaves de guild contrabandeadas sao removidas
    3. guild e re-vinculado ao contexto da interacao
    4. parametros sao validados pela propria ferramenta
    5. cota do plano e rate limit
    6. confirmacao para operacao destrutiva
    7. execucao
    8. verificacao pos-acao contra o Discord

O modelo nao tem nenhum caminho que pule essas etapas.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from .audit import AuditLog
from .errors import ConfirmationRequired, ToolError
from .models import GuildSnapshot
from .policy import DESTRUCTIVE_TOOLS, Policy
from .queue import ActionQueue, ActionResult, PlannedAction
from .tools.base import ToolContext, ToolRegistry

log = logging.getLogger(__name__)


@dataclass
class PreparedPlan:
    actions: list[PlannedAction]
    token: str
    counts: dict[str, int]
    destructive_labels: list[str] = field(default_factory=list)

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.destructive_labels)

    def summary(self) -> str:
        lines = [a.describe() for a in self.actions]
        return "\n".join(f"{i + 1}. {line}" for i, line in enumerate(lines))


class Executor:
    def __init__(
        self,
        *,
        ctx: ToolContext,
        registry: ToolRegistry,
        queue: ActionQueue,
        audit: AuditLog,
        policy: Policy,
    ) -> None:
        self.ctx = ctx
        self.registry = registry
        self.queue = queue
        self.audit = audit
        self.policy = policy

    # ------------------------------------------------------------- preparacao
    def prepare(
        self,
        calls: list[dict[str, Any]],
        *,
        confirm_token: str | None = None,
        require_confirmation: bool = True,
    ) -> PreparedPlan:
        """Valida um lote inteiro ANTES de executar qualquer coisa.

        Com require_confirmation=False o plano e devolvido mesmo precisando de
        confirmacao; quem chama decide parar e perguntar. Isso permite guardar os
        `calls` originais na sessao para reexecutar depois do "sim".
        """
        actions: list[PlannedAction] = []
        destructive_labels: list[str] = []

        for call in calls:
            name = str(call.get("name") or call.get("tool") or "").strip().lower()
            raw_params = call.get("args") or call.get("params") or {}
            if not isinstance(raw_params, dict):
                raise ToolError(
                    f"parametros de {name} nao sao objeto",
                    user_message="O modelo mandou parametros em formato invalido.",
                )

            # 1. politica
            self.policy.check_tool(name)
            tool = self.registry.get(name)

            # 2. chaves de guild contrabandeadas
            params, removed = self.policy.strip_foreign_guild_keys(raw_params)
            if removed:
                log.warning("chaves de guild removidas de %s: %s", name, removed)
                self.audit.record(
                    action="policy.strip_foreign_guild",
                    guild_id=self.ctx.guild_id,
                    params={"tool": name, "removed_keys": removed},
                    result="blocked",
                )

            # 3. guild do contexto, sempre
            self.policy.bind_guild(params.get("guild_id"))

            # 5. parametros exigidos
            required = (tool.parameters or {}).get("required") or []
            missing = [r for r in required if r not in params or params[r] in (None, "")]
            if missing:
                raise ToolError(
                    f"{name} sem parametros obrigatorios: {missing}",
                    user_message=f"Faltou informar: {', '.join(missing)}.",
                )

            label = tool.describe(params)
            actions.append(
                PlannedAction(
                    tool=name,
                    params=params,
                    label=label,
                    call_id=call.get("id"),
                )
            )

            if tool.destructive:
                count = tool.count_destructive(params)
                if count >= 1 and (
                    name in DESTRUCTIVE_TOOLS
                    and sum(1 for a in actions if a.tool in DESTRUCTIVE_TOOLS)
                    >= self.policy.destructive_confirm_threshold
                ):
                    destructive_labels.append(label)
                elif count > 1:
                    destructive_labels.append(f"{label} (x{count})")

        # 5b. cota
        counts = ActionQueue.partition(actions)
        self.policy.check_budget(**counts)

        # 6. confirmacao
        token = self._plan_token(actions)
        destructive_total = sum(1 for a in actions if a.tool in DESTRUCTIVE_TOOLS)
        if destructive_total >= self.policy.destructive_confirm_threshold and require_confirmation:
            if confirm_token != token:
                raise ConfirmationRequired(
                    f"{destructive_total} acoes destrutivas sem confirmacao",
                    summary="\n".join(f"- {l}" for l in destructive_labels),
                    token=token,
                )

        return PreparedPlan(actions=actions, token=token, counts=counts, destructive_labels=destructive_labels)

    @staticmethod
    def _plan_token(actions: list[PlannedAction]) -> str:
        payload = "|".join(f"{a.tool}:{sorted(a.params.items())}" for a in actions)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    # --------------------------------------------------------------- execucao
    def execute(self, plan: PreparedPlan) -> list[ActionResult]:
        results: list[ActionResult] = []
        for action in plan.actions:
            result = self.queue.run_one(action)
            if result.ok and result.verified is False:
                result.user_message = (
                    "A chamada nao deu erro, mas quando voltei para conferir o estado no Discord "
                    "a alteracao nao estava la. Nao vou dizer que funcionou."
                )
                self.audit.record(
                    action=f"{action.tool}.verification_failed",
                    guild_id=self.ctx.guild_id,
                    params=action.params,
                    result="unverified",
                )
            results.append(result)
        return results

    # -------------------------------------------------------------- dispatch
    def dispatch(self, action: PlannedAction) -> dict[str, Any]:
        """Chamado pela fila. Executa UMA acao ja validada e confere depois."""
        tool = self.registry.get(action.tool)
        self.policy.check_tool(action.tool)

        params, removed = self.policy.strip_foreign_guild_keys(action.params)
        if removed:
            self.audit.record(
                action="policy.strip_foreign_guild",
                guild_id=self.ctx.guild_id,
                params={"tool": action.tool, "removed_keys": removed},
                result="blocked",
            )
        self.policy.bind_guild(params.get("guild_id"))

        # ferramenta sempre le do snapshot mais recente
        self.ctx.refresh()

        try:
            data = tool.handler(self.ctx, params)
        except ValueError as exc:
            raise ToolError(str(exc), user_message=f"Parametro invalido: {exc}") from exc

        if not isinstance(data, dict):
            data = {"result": data}

        verified: bool | None = None
        if tool.verify is not None:
            try:
                verified = bool(tool.verify(self.ctx, params, data))
            except Exception as exc:  # noqa: BLE001
                log.warning("verificacao de %s falhou: %s", action.tool, exc)
                verified = False
            data["verified"] = verified

        data["tool"] = action.tool
        data["label"] = action.label
        return data

    # ------------------------------------------------------------ utilidades
    @property
    def snapshot(self) -> GuildSnapshot:
        return self.ctx.snapshot

    def refresh(self) -> GuildSnapshot:
        return self.ctx.refresh()
