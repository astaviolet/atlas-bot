"""Converte resultado de execucao em embeds. Nunca sai texto puro daqui."""

from __future__ import annotations

from typing import Any, Sequence

from .task import resumo_da_tarefa

from .embeds import EmbedBuilder, EmbedField, EmbedKind, EmbedSpec
from .queue import ActionResult


def _group(results: Sequence[ActionResult]) -> tuple[list[ActionResult], list[ActionResult]]:
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    return ok, failed


def result_embeds(builder: EmbedBuilder, results: Sequence[ActionResult]) -> list[EmbedSpec]:
    """So o essencial. O usuario pediu para nao receber informacao desnecessaria.

    Quando tudo deu certo, isto devolve so o checklist - que merge_embeds
    descarta se o modelo ja escreveu o que fez. Ou seja: na pratica o usuario
    ve "Apaguei o canal." e nada mais.

    O aviso de nao-confirmado vai em embed proprio, de proposito: se ele for
    colado no checklist, o checklist deixa de ser "so checklist" e o descarte
    nao acontece - foi assim que "- get_server_info" e "Acoes: 2" vazaram.
    """
    if not results:
        return []

    ok, failed = _group(results)
    embeds: list[EmbedSpec] = []

    if ok:
        body = "\n".join(f"- {r.action.describe()}" for r in ok)
        embeds.append(builder.build(EmbedKind.SUCCESS, "", body))

    unverified = [r for r in ok if r.verified is False]
    if unverified:
        nomes = ", ".join(r.action.describe() for r in unverified[:3])
        embeds.append(
            builder.warning(
                "", f"Nao consegui confirmar: {nomes}. Confere se ficou como voce queria."
            )
        )

    if failed and ok:
        # Sucesso parcial tem que dizer a conta (spec 22): "16 de 18" nao e
        # "tudo pronto". Linha propria, curta.
        embeds.append(builder.warning("", resumo_da_tarefa(results)))

    if failed:
        linhas = []
        for r in failed[:5]:
            linhas.append(f"{r.action.describe()}: {r.user_message or 'falhou'}")
        if len(failed) > 5:
            linhas.append(f"e mais {len(failed) - 5}")
        embeds.append(builder.error("", "\n".join(linhas)))

    return embeds


def plan_embed(builder: EmbedBuilder, steps: Sequence[str], *, note: str = "") -> EmbedSpec:
    description = note
    return builder.plan("Plano", list(steps), description=description)


def confirmation_embed(builder: EmbedBuilder, summary: str, destructive_count: int) -> EmbedSpec:
    return builder.confirm(
        "Preciso de confirmacao",
        f"Isso vai **excluir {destructive_count} item(ns)** e nao da para desfazer pelo bot.\n\n"
        f"{summary}\n\nResponda **sim** para executar ou **nao** para cancelar.",
        fields=[EmbedField("Itens afetados", str(destructive_count), inline=True)],
    )


def error_embed(builder: EmbedBuilder, exc: Exception) -> EmbedSpec:
    user_message = getattr(exc, "user_message", None) or str(exc)
    return builder.error("Nao foi possivel executar", user_message)


def refusal_embed(builder: EmbedBuilder, reason: str, *, hint: str = "") -> EmbedSpec:
    fields = [EmbedField("O que posso fazer", hint)] if hint else None
    return builder.warning("Isso eu nao faco", reason, fields=fields)


def injection_embed(builder: EmbedBuilder, hits: Sequence[str]) -> EmbedSpec:
    return builder.warning(
        "Isso nao muda nada aqui",
        "Mensagens na conversa nao alteram minhas regras. Continuo sem moderar pessoas e sem sair deste servidor.",
        fields=[EmbedField("Detectado", "; ".join(hits) if hits else "tentativa de sobrescrever regras")],
    )


def state_embed(builder: EmbedBuilder, snapshot: Any) -> EmbedSpec:
    categories = snapshot.category_channels()
    channels = [c for c in snapshot.channels if not c.is_category]
    return builder.info(
        snapshot.name,
        snapshot.description or "_sem descricao_",
        fields=[
            EmbedField("Categorias", str(len(categories)), inline=True),
            EmbedField("Canais", str(len(channels)), inline=True),
            EmbedField("Cargos", str(len(snapshot.roles)), inline=True),
        ],
    )
