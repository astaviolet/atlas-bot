"""Converte resultado de execucao em embeds. Nunca sai texto puro daqui."""

from __future__ import annotations

from typing import Any, Sequence

from .embeds import EmbedBuilder, EmbedField, EmbedKind, EmbedSpec
from .queue import ActionResult


def _group(results: Sequence[ActionResult]) -> tuple[list[ActionResult], list[ActionResult]]:
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    return ok, failed


def result_embeds(builder: EmbedBuilder, results: Sequence[ActionResult]) -> list[EmbedSpec]:
    """Um embed de resumo + um de detalhes quando houver falha."""
    if not results:
        return [builder.info("Nada executado", "Esse pedido nao gerou nenhuma acao.")]

    ok, failed = _group(results)
    embeds: list[EmbedSpec] = []

    if ok and not failed:
        lines = [r.action.describe() for r in ok]
        body = "\n".join(f"`✓` {line}" for line in lines)
        unverified = [r for r in ok if r.verified is False]
        kind = EmbedKind.WARNING if unverified else EmbedKind.SUCCESS
        embed = builder.build(
            kind,
            "Configuracao concluida" if len(ok) > 1 else "Feito",
            body,
            fields=[EmbedField("Acoes", str(len(ok)), inline=True)],
        )
        if unverified:
            embed.description += (
                f"\n\n**{len(unverified)} acao(oes) nao puderam ser confirmadas** ao conferir o servidor depois."
            )
        embeds.append(embed)
        return embeds

    if ok:
        body = "\n".join(f"`✓` {r.action.describe()}" for r in ok)
        embeds.append(builder.build(EmbedKind.RESULT, "Concluido em parte", body,
                                    fields=[EmbedField("Funcionaram", str(len(ok)), inline=True),
                                            EmbedField("Falharam", str(len(failed)), inline=True)]))

    if failed:
        rows = []
        for r in failed[:20]:
            detail = r.user_message or r.error or "erro desconhecido"
            rows.append(f"**{r.action.describe()}**\n{detail}")
        embeds.append(
            builder.error(
                "Nao consegui executar" if not ok else "Essas partes falharam",
                "\n\n".join(rows),
                fields=[EmbedField("Total de falhas", str(len(failed)), inline=True)],
            )
        )
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
