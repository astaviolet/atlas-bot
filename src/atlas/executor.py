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
from .design_check import checar_plano
from .flow_control import Backpressure, GuildQuota
from .snapshot_store import SnapshotStore
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
    #: Preenchido pelo Executor quando o plano precisa de confirmacao. Guarda o
    #: texto pronto para mostrar. Centralizar aqui evita ter a mesma decisao
    #: escrita em dois lugares - foi assim que a construcao grande ficou de fora.
    confirm_summary: str = ""

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.confirm_summary)

    def summary(self) -> str:
        lines = [a.describe() for a in self.actions]
        return "\n".join(f"{i + 1}. {line}" for i, line in enumerate(lines))

    def dry_run(self) -> str:
        """Resumo do que vai acontecer, sem executar nada (spec 12).

        Agrupado por verbo e tipo: "criar 8 categorias, 27 canais" diz mais do
        que 35 linhas de acao, e e o que a pessoa precisa para decidir.
        """
        alvos = {"category": "categoria", "channel": "canal", "role": "cargo",
                 "server": "servidor"}
        grupos: dict[str, int] = {}
        for a in self.actions:
            verbo = "criar" if a.tool.startswith("create_") else (
                "remover" if a.tool in DESTRUCTIVE_TOOLS else "alterar"
            )
            cru = a.tool.split("_", 1)[1] if "_" in a.tool else a.tool
            chave = f"{verbo} {alvos.get(cru, cru)}"
            grupos[chave] = grupos.get(chave, 0) + 1
        partes = [f"{qt} {nome}" for nome, qt in sorted(grupos.items())]
        return ", ".join(partes) if partes else "nada"


class Executor:
    def __init__(
        self,
        *,
        ctx: ToolContext,
        registry: ToolRegistry,
        queue: ActionQueue,
        audit: AuditLog,
        policy: Policy,
        snapshots: SnapshotStore | None = None,
        flow: Backpressure | None = None,
        quota: GuildQuota | None = None,
    ) -> None:
        self.ctx = ctx
        self.snapshots = snapshots or SnapshotStore()
        limites = ctx.limits
        self.flow = flow or Backpressure(
            limites.backpressure_max_acoes, limites.backpressure_max_guilds,
        )
        self.quota = quota or GuildQuota(
            limites.fairness_max_acoes, limites.fairness_janela_segundos,
        )
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
        # 5b. qualidade objetiva do plano (spec 47). Roda antes de qualquer
        # chamada ao Discord: plano ruim nao deve gastar rate limit para depois
        # ser desfeito. So defeito objetivo - duplicata, orfao, cargo novo com
        # permissao administrativa. Estetica nao se valida em codigo.
        problemas = checar_plano(actions, self.ctx.snapshot)
        if problemas:
            log.warning("plano rejeitado: %s", problemas)
            self.audit.record(
                action="design.plan_rejected",
                guild_id=self.ctx.guild_id,
                params={"problemas": problemas[:10]},
                result="blocked",
            )
            raise ToolError(
                "plano com defeito",
                user_message="O plano tinha problema e nao executei nada: "
                + "; ".join(problemas[:4]),
            )

        counts = ActionQueue.partition(actions)
        self.policy.check_budget(**counts)

        # 5c. backpressure (spec 149). Recusar AQUI, e nao no meio da execucao:
        # quando o modelo ja planejou, o custo de IA esta pago. Recusar cedo e
        # mais barato e mais honesto do que comecar e morrer na acao 300.
        if not self.flow.plano_cabe(counts.get("actions", 0)):
            self.audit.record(
                action="flow.backpressure", guild_id=self.ctx.guild_id,
                params={"acoes": counts.get("actions", 0),
                        "teto": self.flow.max_pendentes_por_guild},
                result="blocked",
            )
            raise ToolError(
                f"plano de {counts.get('actions', 0)} acoes passa do teto de "
                f"{self.flow.max_pendentes_por_guild}",
                user_message=(
                    f"Esse pedido virou {counts.get('actions', 0)} acoes de uma vez. "
                    f"Meu teto e {self.flow.max_pendentes_por_guild} por vez - vamos por partes?"
                ),
            )

        # 5d. fairness (spec 150). Cota por guild em janela deslizante: um
        # servidor nao pode consumir o pool inteiro enquanto outro espera.
        if self.quota.estourou(self.ctx.guild_id):
            espera = self.quota.espera_restante(self.ctx.guild_id)
            self.audit.record(
                action="flow.quota_exceeded", guild_id=self.ctx.guild_id,
                params={"usadas": self.quota.usadas(self.ctx.guild_id),
                        "teto": self.quota.max_acoes, "espera_s": round(espera, 1)},
                result="blocked",
            )
            raise ToolError(
                f"cota de {self.quota.max_acoes} acoes/{self.quota.window_seconds:.0f}s esgotada",
                user_message=(
                    f"Este servidor ja usou as {self.quota.max_acoes} acoes desta janela. "
                    f"Libera em {int(espera) + 1}s - assim os outros servidores nao ficam esperando."
                ),
            )
        self.quota.admitir(self.ctx.guild_id, counts.get("actions", 0))

        # 6. confirmacao
        token = self._plan_token(actions)
        resumo_dry = PreparedPlan(actions=actions, token=token, counts=counts).dry_run()
        destructive_total = sum(1 for a in actions if a.tool in DESTRUCTIVE_TOOLS)
        cria_total = counts.get("creates", 0)
        limiar_destrutivo = self.policy.destructive_confirm_threshold
        limiar_construcao = self.ctx.limits.build_confirm_threshold
        precisa = (
            destructive_total >= limiar_destrutivo or cria_total >= limiar_construcao
        )
        confirm_summary = ""
        if precisa and confirm_token != token:
            # Mostra o plano inteiro, nao so as exclusoes: construcao grande
            # tambem merece ser vista antes (spec 12/133).
            linhas = [f"Plano: {resumo_dry}"]
            linhas.extend(f"- {l}" for l in destructive_labels)
            confirm_summary = "\n".join(linhas)
            if require_confirmation:
                raise ConfirmationRequired(
                    f"plano grande sem confirmacao ({destructive_total} remocoes, "
                    f"{cria_total} criacoes)",
                    summary=confirm_summary,
                    token=token,
                )

        return PreparedPlan(
            actions=actions, token=token, counts=counts,
            destructive_labels=destructive_labels, confirm_summary=confirm_summary,
        )

    @staticmethod
    def _plan_token(actions: list[PlannedAction]) -> str:
        payload = "|".join(f"{a.tool}:{sorted(a.params.items())}" for a in actions)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    # --------------------------------------------------------------- execucao
    def execute(self, plan: PreparedPlan) -> list[ActionResult]:
        # Snapshot logico ANTES de mudar (spec 86). Aqui, e nao no agente,
        # porque ha dois caminhos de execucao - o laco normal e o que roda
        # depois do "sim". Instrumentar so um deixava sem snapshot justamente
        # os planos grandes, que sao os que passam por confirmacao.
        if len(plan.actions) >= self.ctx.limits.snapshot_threshold:
            try:
                self.snapshots.salvar(
                    self.ctx.guild_id, self.ctx.snapshot,
                    autor=self.ctx.source_author_name or "?",
                    resumo=plan.dry_run(),
                )
            except Exception:  # noqa: BLE001 - diagnostico nunca impede a operacao
                log.warning("snapshot nao salvo; seguindo sem ele", exc_info=True)

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
