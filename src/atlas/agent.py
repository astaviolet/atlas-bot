"""Agente. Faz o laco modelo <-> ferramentas, sempre passando pelo executor.

O modelo decide *o que* pedir. O executor decide *se pode*. Essa separacao e o
que impede que uma mensagem do usuario, por mais convincente, produza uma acao
proibida.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .ai import ModelClient, ensure_call_ids
from .audit import AuditLog
from .config import Limits
from .design_check import auditar_servidor
from .ai.classificacao import classificar
from .estados import AgentState, RastreadorDeEstado
from .snapshot_store import SnapshotStore
from .task import TaskState, estado_da_tarefa
from .embeds import EmbedBuilder, EmbedKind, EmbedSpec
from .errors import AIError, AtlasError, ConfirmationRequired
from .executor import Executor
from .formatting import (
    confirmation_embed,
    error_embed,
    injection_embed,
    result_embeds,
)
from .policy import Policy, is_read_only
from .prompts import build_system_prompt
from .queue import ActionQueue, ActionResult
from .session import Session, PendingConfirmation, classify_reply
from .tools.base import ToolContext, ToolRegistry

log = logging.getLogger(__name__)

MAX_EMBEDS_PER_TURN = 3

#: Prioridade de sobrevivencia quando ha mais embeds do que cabem na resposta.
#: O corte por POSICAO (embeds[:3]) era errado de dois jeitos, os dois reais:
#:  - a resposta do modelo vinha por ultimo e era a primeira a sumir, entao o
#:    usuario ficava sem o "Pronto." justamente quando houve erro para explicar;
#:  - o embed de erro tambem e acrescentado no fim, e sumia junto.
#: Aqui o que importa mais sobrevive, e a ORDEM DE EXIBICAO e preservada.
_PRIORIDADE_EMBED = {
    EmbedKind.ERROR: 0,
    EmbedKind.WARNING: 1,
    EmbedKind.RESULT: 2,
    EmbedKind.SUCCESS: 3,
    EmbedKind.INFO: 4,
}


def _cortar_por_prioridade(embeds: list[EmbedSpec], limite: int) -> list[EmbedSpec]:
    """Mantem os `limite` mais importantes, na ordem original de exibicao."""
    if len(embeds) <= limite:
        return embeds
    # a resposta do modelo (info com texto curto) nao tem como ser distinguida de
    # um info qualquer, entao ela entra marcada pelo chamador com _protegido
    protegidos = [i for i, e in enumerate(embeds) if getattr(e, 'protegido', False)]
    resto = [i for i in range(len(embeds)) if i not in protegidos]
    resto.sort(key=lambda i: (_PRIORIDADE_EMBED.get(embeds[i].kind, 9), i))
    manter = set(protegidos[:limite])
    for i in resto:
        if len(manter) >= limite:
            break
        manter.add(i)
    return [e for i, e in enumerate(embeds) if i in manter]





@dataclass
class AgentOutcome:
    embeds: list[EmbedSpec] = field(default_factory=list)
    results: list[ActionResult] = field(default_factory=list)
    blocked: str | None = None
    #: Estado final do agente (spec 113) e o caminho percorrido.
    estado: str | None = None
    caminho: list[str] = field(default_factory=list)

    @property
    def state(self) -> "TaskState":
        """Estado final da tarefa (spec 89). Derivado, nao guardado: assim ele
        nunca diverge do que realmente aconteceu."""
        return estado_da_tarefa(self.results, self.blocked)


class Agent:
    def __init__(
        self,
        *,
        ctx: ToolContext,
        registry: ToolRegistry,
        executor: Executor,
        model: ModelClient,
        builder: EmbedBuilder,
        audit: AuditLog,
        policy: Policy,
        limits: Limits,
    ) -> None:
        self.estado = RastreadorDeEstado()
        self.ctx = ctx
        self.registry = registry
        self.executor = executor
        self.model = model
        self.builder = builder
        self.audit = audit
        self.policy = policy
        self.limits = limits

    def _com_estado(self, out: "AgentOutcome") -> "AgentOutcome":
        """Carimba estado e caminho (spec 113). O caminho vai junto porque
        COMPLETED sozinho nao diz se houve verificacao nem recuperacao.

        O estado terminal e DERIVADO do resultado, nao declarado em cada return:
        _handle_interno tem mais de dez saidas e declarar uma a uma ia deixar
        alguma marcando COMPLETED sem ter executado - o sucesso falso da spec 185.
        """
        atual = self.estado.estado
        if atual not in (AgentState.WAITING_CONFIRMATION, AgentState.FAILED):
            if atual in (AgentState.UNDERSTANDING, AgentState.PLANNING,
                         AgentState.EXECUTING, AgentState.VERIFYING,
                         AgentState.RECOVERING):
                tudo_falhou = bool(out.results) and not any(r.ok for r in out.results)
                self.estado.ir_para(
                    AgentState.FAILED if tudo_falhou else AgentState.COMPLETED
                )
        out.estado = self.estado.estado.value
        out.caminho = [e for e, _ in self.estado.historico]
        return out

    # ------------------------------------------------------------------ API
    async def handle(self, text: str, session: Session) -> AgentOutcome:
        """Processa uma mensagem do usuario e devolve os embeds a enviar.

        Wrapper fino de proposito: _handle_interno tem mais de dez pontos de
        retorno, e carimbar o estado em cada um ia escapar por algum. Aqui todo
        caminho sai com estado (spec 113), inclusive o que levanta.
        """
        self.estado.reiniciar()
        self.estado.ir_para(AgentState.UNDERSTANDING)
        try:
            return self._com_estado(await self._handle_interno(text, session))
        except Exception:
            self.estado.ir_para(AgentState.FAILED)
            raise

    async def _handle_interno(self, text: str, session: Session) -> AgentOutcome:
        screening = self.policy.screen_user_text(text)
        if screening["unicode_issues"]:
            log.warning("unicode suspeito na mensagem: %s", screening["unicode_issues"])
            self.audit.record(
                action="screen.unicode",
                guild_id=self.ctx.guild_id,
                channel_id=session.channel_id,
                params={"issues": screening["unicode_issues"]},
                result="flagged",
            )

        # 1. tentativa de tomada de controle -> recusa direta, nao roda o modelo
        if screening["injection_hits"]:
            self.audit.record(
                action="screen.injection",
                guild_id=self.ctx.guild_id,
                channel_id=session.channel_id,
                params={"hits": screening["injection_hits"]},
                result="blocked",
            )
            self.estado.ir_para(AgentState.FAILED)
            return AgentOutcome(
                embeds=[injection_embed(self.builder, screening["injection_hits"])],
                blocked="prompt_injection",
            )

        # 2. confirmacao pendente?
        if session.pending is not None:
            return await self._resolve_confirmation(text, session)

        # 3. fluxo normal
        try:
            return await self._run_loop(text, session)
        except ConfirmationRequired as exc:
            # defensivo: o laco trata confirmacao antes de executar, entao chegar
            # aqui significa um caminho que nao passou por _run_loop.
            log.warning("ConfirmationRequired escapou do laco: %s", exc)
            return AgentOutcome(
                embeds=[confirmation_embed(self.builder, exc.summary, _count_lines(exc.summary))],
                blocked="confirmation_required",
            )
        except AIError as exc:
            self.audit.record(
                action="ai.error",
                guild_id=self.ctx.guild_id,
                channel_id=session.channel_id,
                result="error",
                error=str(exc),
            )
            return AgentOutcome(embeds=[error_embed(self.builder, exc)])
        except AtlasError as exc:
            self.audit.record(
                action="agent.error",
                guild_id=self.ctx.guild_id,
                channel_id=session.channel_id,
                result="error",
                error=str(exc),
            )
            return AgentOutcome(embeds=[error_embed(self.builder, exc)])
        except Exception as exc:  # noqa: BLE001 - ultima barreira antes do Discord
            log.exception("erro inesperado no agente")
            self.audit.record(
                action="agent.unexpected",
                guild_id=self.ctx.guild_id,
                channel_id=session.channel_id,
                result="error",
                error=f"{type(exc).__name__}: {exc}",
            )
            return AgentOutcome(
                embeds=[self.builder.error("Algo quebrou aqui", "Deu um erro inesperado do meu lado. Tenta de novo.")]
            )

    # ------------------------------------------------------------ confirmacao
    async def _resolve_confirmation(self, text: str, session: Session) -> AgentOutcome:
        # Prazo antes de qualquer outra coisa: um "sim" que chegou tarde demais
        # nao executa nada, nem mesmo para cancelar. Descarta e pede de novo.
        if session.confirmacao_vencida():
            session.pending = None
            return AgentOutcome(
                embeds=[
                    self.builder.warning(
                        "Passou do prazo",
                        "A confirmacao expirou, entao nao fiz nada. Me pede de novo.",
                    )
                ],
                blocked="confirmation_expired",
            )

        pending = session.pending
        assert pending is not None
        verdict = classify_reply(text)

        if verdict == "no":
            session.pending = None
            return AgentOutcome(
                embeds=[self.builder.info("Cancelado", "Nada foi excluido.")]
            )

        if verdict != "yes":
            return AgentOutcome(
                embeds=[
                    self.builder.confirm(
                        "Ainda esperando",
                        f"Tem {pending.summary.count(chr(10)) + 1} exclusao(oes) na fila.\n\n"
                        f"{pending.summary}\n\nResponda **sim** ou **nao**.",
                    )
                ],
                blocked="awaiting_confirmation",
            )

        session.pending = None
        try:
            plan = self.executor.prepare(pending.calls, confirm_token=pending.token)
        except ConfirmationRequired:
            # nao deve acontecer: o token e derivado do proprio plano
            return AgentOutcome(
                embeds=[self.builder.error("Confirmacao expirou", "Monte o pedido de novo, por favor.")]
            )
        except AtlasError as exc:
            return AgentOutcome(embeds=[error_embed(self.builder, exc)])

        results = self.executor.execute(plan)
        self.audit.record(
            action="confirmation.granted",
            guild_id=self.ctx.guild_id,
            channel_id=session.channel_id,
            params={"actions": len(plan.actions)},
            result="ok",
        )
        session.add_function_results([_result_payload(r) for r in results])
        return AgentOutcome(embeds=_cortar_por_prioridade(result_embeds(self.builder, results), MAX_EMBEDS_PER_TURN), results=results)

    # --------------------------------------------------------------------- QA
    def _qa_pos_execucao(
        self, results: list[ActionResult], pedido: str = ""
    ) -> list[EmbedSpec]:
        """Conferir o estado REAL depois de mexer (spec 24, 138).

        So roda quando algo mudou - ler o servidor nao precisa de QA. E so
        reporta defeito objetivo: categoria vazia, canal orfao, duplicata.
        Nao opina sobre estetica; isso nao se decide em codigo.
        """
        # So em construcao de verdade (>= 3 mudancas). Criar UMA categoria agora
        # e por os canais dentro na volta seguinte e fluxo normal, nao defeito -
        # avisar "categoria vazia" ali seria alarme falso.
        mudancas = [r for r in results if r.ok and not is_read_only(r.action.tool)]
        if len(mudancas) < 3:
            return []
        self.estado.ir_para(AgentState.VERIFYING)
        try:
            snapshot = self.ctx.refresh()
        except Exception:  # noqa: BLE001 - QA nunca derruba a resposta
            log.warning("QA pos-execucao nao conseguiu reler o servidor", exc_info=True)
            return []
        problemas = auditar_servidor(snapshot)
        # Spec 138: alem do defeito objetivo, comparar com o que foi PROJETADO.
        # Um servidor pode estar sem categoria vazia e mesmo assim nao ser o que
        # o pedido pedia.
        problemas = [*problemas, *_faltas_contra_o_design(snapshot, pedido)]
        if not problemas:
            return []
        log.info("QA pos-execucao achou %d problema(s): %s", len(problemas), problemas)
        return [
            self.builder.warning(
                "",
                "Conferindo depois: " + "; ".join(problemas[:2]),
            )
        ]

    # ------------------------------------------------------------ laco do modelo
    async def _run_loop(self, text: str, session: Session) -> AgentOutcome:
        # Spec 107: classificar uma vez, antes da primeira chamada. O tamanho do
        # contexto entra na conta porque conversa longa muda o que a rota aguenta.
        classe_tarefa = classificar(
            text,
            vai_usar_tools=True,
            tam_contexto=sum(len(str(m.get("content") or "")) for m in session.history),
        )
        self.audit.record(
            action="ai.task_class",
            guild_id=self.ctx.guild_id,
            params={"classe": classe_tarefa.value, "chars_pedido": len(text)},
            result="ok",
        )
        self.ctx.refresh()
        system = build_system_prompt(
            self.ctx.snapshot, self.registry, self.policy,
            source_channel_id=self.ctx.source_channel_id,
            source_author_id=self.ctx.source_author_id,
            source_author_name=self.ctx.source_author_name,
            request=text,
        )
        declarations = self.registry.declarations()

        session.add_user(text)
        all_results: list[ActionResult] = []
        comeco = time.monotonic()

        for turn in range(self.limits.max_turns):
            # Prazo total. Sem isto o pior caso era max_turns x timeout da IA
            # (25 x 60s = 25 minutos) e o usuario ficava olhando o bot "pensar"
            # sem nunca receber resposta. Melhor entregar o que ja foi feito.
            if time.monotonic() - comeco > self.limits.deadline_seconds:
                log.warning(
                    "prazo de %.0fs esgotado no turno %d", self.limits.deadline_seconds, turn
                )
                embeds = result_embeds(self.builder, all_results) if all_results else []
                embeds.append(
                    self.builder.warning(
                        "",
                        "Demorou demais e eu parei aqui. O que ja estava feito ficou "
                        "feito; me diz se quer que eu continue.",
                    )
                )
                return AgentOutcome(embeds=_cortar_por_prioridade(embeds, MAX_EMBEDS_PER_TURN), results=all_results)

            response = ensure_call_ids(
                self.model.generate(
                    system=system,
                    history=session.history,
                    tools=declarations,
                    guild_id=self.ctx.guild_id,
                    classe=classe_tarefa,
                ),
                turn_index=turn,
            )

            self.estado.ir_para(AgentState.PLANNING)
            if not response.wants_tools:
                if response.text:
                    session.add_assistant_text(response.text)
                embeds = result_embeds(self.builder, all_results) if all_results else []
                if response.text:
                    resposta = self.builder.info("Atlas", response.text)
                    resposta.protegido = True
                    embeds.append(resposta)
                if not embeds:
                    embeds = [self.builder.info("Atlas", "Nao encontrei nada para fazer nesse pedido.")]
                # Spec 138 tambem na conclusao normal. Antes o QA so rodava no
                # caminho de limite de turnos, ou seja: quando tudo dava certo
                # ninguem conferia o resultado.
                embeds.extend(self._qa_pos_execucao(all_results, text))
                return AgentOutcome(embeds=_cortar_por_prioridade(embeds, MAX_EMBEDS_PER_TURN), results=all_results)

            calls = [{"id": c.id, "name": c.name, "args": c.args} for c in response.calls]
            session.add_model_calls(calls)

            # require_confirmation=False: o plano volta para que a gente possa
            # guardar os `calls` reais e reexecutar depois do "sim".
            plan = self.executor.prepare(calls, require_confirmation=False)

            # A decisao de "precisa confirmar" e do Executor, nao daqui.
            # Antes este bloco recontava so as exclusoes e deixava passar
            # construcao grande (spec 12).
            if plan.needs_confirmation:
                self.estado.ir_para(AgentState.WAITING_CONFIRMATION)
                summary = plan.confirm_summary
                session.pending = PendingConfirmation(
                    token=plan.token, calls=calls, summary=summary,
                    created_at=session.clock(),
                )
                return AgentOutcome(
                    embeds=[confirmation_embed(self.builder, summary, _count_lines(summary))],
                    blocked="confirmation_required",
                )

            self.estado.ir_para(AgentState.EXECUTING)
            results = self.executor.execute(plan)
            all_results.extend(results)
            session.add_function_results([_result_payload(r) for r in results])

            # Se algo mudou no servidor, a resposta guardada ja nao descreve a
            # realidade: descarta o cache deste guild. So leitura nao invalida.
            if any(not is_read_only(r.action.tool) for r in results):
                invalidar = getattr(self.model, "invalidar_guild", None)
                if invalidar is not None:
                    invalidar(self.ctx.guild_id)

            # memoria de objetos criados, para "agora de permissao a ele"
            for result in results:
                _remember_created(session, result)

        log.warning("limite de %d turnos atingido", self.limits.max_turns)
        embeds = result_embeds(self.builder, all_results) if all_results else []
        embeds.extend(self._qa_pos_execucao(all_results, text))
        embeds.append(
            self.builder.warning(
                "Parei no meio",
                f"Cheguei ao limite de {self.limits.max_turns} rodadas internas nessa solicitacao. "
                "O que ja estava feito ficou feito; o resto precisa de outro pedido.",
            )
        )
        return AgentOutcome(embeds=_cortar_por_prioridade(embeds, MAX_EMBEDS_PER_TURN), results=all_results)


# --------------------------------------------------------------------- utils
def _count_lines(summary: str) -> int:
    return len([l for l in summary.splitlines() if l.strip()])


def _result_payload(result: ActionResult) -> dict[str, Any]:
    """O que volta para o modelo. Sem dado sensivel, com status de verificacao.

    O `id` casa esta resposta com a tool call que a originou; sem ele o provedor
    rejeita a conversa no turno seguinte.
    """
    if result.ok:
        data = result.data if isinstance(result.data, dict) else {"result": result.data}
        return {
            "id": result.action.call_id,
            "name": result.action.tool,
            "response": {
                "status": "ok",
                "verified": data.get("verified"),
                "detail": {k: v for k, v in data.items() if k not in ("tool", "label")},
            },
        }
    return {
        "id": result.action.call_id,
        "name": result.action.tool,
        "response": {
            "status": "error",
            "error_kind": result.error_kind,
            "error": result.user_message or result.error,
        },
    }


def _remember_created(session: Session, result: ActionResult) -> None:
    if not result.ok or not isinstance(result.data, dict):
        return
    tool = result.action.tool
    if tool == "create_role":
        role = result.data.get("created") or {}
        if role.get("name") and role.get("id"):
            session.remember("role", str(role["name"]), str(role["id"]))
    elif tool in ("create_channel", "create_category"):
        channel = result.data.get("created") or {}
        if channel.get("name") and channel.get("id"):
            session.remember("channel", str(channel["name"]), str(channel["id"]))


def build_agent(
    *,
    ctx: ToolContext,
    registry: ToolRegistry,
    model: ModelClient,
    builder: EmbedBuilder,
    audit: AuditLog,
    policy: Policy,
    limits: Limits,
    queue: ActionQueue,
    snapshots: SnapshotStore | None = None,
) -> Agent:
    executor = Executor(
        ctx=ctx, registry=registry, queue=queue, audit=audit, policy=policy,
        snapshots=snapshots,
    )
    return Agent(
        ctx=ctx,
        registry=registry,
        executor=executor,
        model=model,
        builder=builder,
        audit=audit,
        policy=policy,
        limits=limits,
    )


def _faltas_contra_o_design(snapshot: Any, pedido: str) -> list[str]:
    """Projeta o design que o pedido implicava e compara com o estado real.

    Devolve lista vazia quando o pedido não é de design — não faz sentido
    comparar "cite os cargos" com uma arquitetura projetada.
    """
    from .design import is_pedido_de_design, is_pedido_de_reforma
    from .design_check import conferir_contra_design
    from .design_system import Briefing, inferir_dominio, inferir_estilo, inferir_porte, projetar

    if not pedido:
        return []
    if not (is_pedido_de_design(pedido) or is_pedido_de_reforma(pedido)):
        return []
    try:
        n_membros = getattr(getattr(snapshot, "guild", None), "member_count", None)
        arquitetura = projetar(Briefing(
            tema=pedido,
            dominio=inferir_dominio(pedido),
            porte=inferir_porte(n_membros),
            estilo=inferir_estilo(pedido),
        ))
        return conferir_contra_design(snapshot, arquitetura)
    except Exception:  # noqa: BLE001 - QA nunca derruba a resposta
        log.warning("comparacao com o design projetado falhou", exc_info=True)
        return []
