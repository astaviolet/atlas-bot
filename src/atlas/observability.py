"""Observabilidade: uma visao agregada de Discord, IA, fila e estado de tarefa.

Spec 121: "Uma camada so que mostra Discord, IA, queue, tools e estado."
Spec 122: "Um painel que responde: o que aconteceu? onde falhou? o que agora?"

Nao duplica nada: o painel de IA ja existe (`ai.stats.PoolStats.snapshot` +
`ai.formatar_painel`). Aqui entra o que faltava - o lado das acoes - e o
agregador que junta os dois.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Sequence


def resumo_auditoria(registros: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Conta o que o log de auditoria diz. Nunca levanta."""
    por_acao: Counter[str] = Counter()
    por_resultado: Counter[str] = Counter()
    guilds: set[int] = set()
    erros: list[dict[str, str]] = []

    for r in registros:
        if not isinstance(r, dict):
            continue
        por_acao[str(r.get("action") or "?")] += 1
        resultado = str(r.get("result") or "?")
        por_resultado[resultado] += 1
        gid = r.get("guild_id")
        if gid is not None:
            guilds.add(int(gid))
        if resultado != "ok":
            erros.append({
                "action": str(r.get("action") or "?"),
                "result": resultado,
                "error": str(r.get("error") or "")[:160],
            })

    total = sum(por_resultado.values())
    falhas = total - por_resultado.get("ok", 0)
    # o ultimo que e dict de fato: log em disco pode ter linha corrompida
    ultimo = None
    for r in reversed(list(registros)):
        if isinstance(r, dict) and r.get("iso"):
            ultimo = r["iso"]
            break

    return {
        "total_eventos": total,
        "ok": por_resultado.get("ok", 0),
        "falhas": falhas,
        "taxa_de_falha": round(falhas / total, 3) if total else 0.0,
        "guilds_distintos": len(guilds),
        "por_acao": dict(por_acao.most_common()),
        "por_resultado": dict(por_resultado.most_common()),
        "ultimos_erros": erros[-5:],
        "ultima_atividade": ultimo,
    }


def responder_as_tres_perguntas(resumo: dict[str, Any], ai: dict[str, Any] | None = None) -> list[str]:
    """Spec 122, ao pe da letra: o que aconteceu? onde falhou? o que agora?

    Texto curto de proposito - painel que precisa de legenda nao e painel.
    """
    linhas = []

    total = resumo.get("total_eventos", 0)
    if total == 0:
        linhas.append("o que aconteceu: nada registrado ainda.")
    else:
        top = ", ".join(f"{a} ({n})" for a, n in list(resumo.get("por_acao", {}).items())[:3])
        linhas.append(
            f"o que aconteceu: {total} eventos, {resumo['ok']} ok / {resumo['falhas']} falha "
            f"em {resumo['guilds_distintos']} servidor(es). Topo: {top}."
        )

    erros = resumo.get("ultimos_erros") or []
    if not erros:
        linhas.append("onde falhou: em nada.")
    else:
        detalhe = "; ".join(
            f"{e['action']} -> {e['error'] or e['result']}" for e in erros[-3:]
        )
        linhas.append(f"onde falhou: {detalhe}")

    if ai:
        rotas = ai.get("rotas")
        saudaveis = ai.get("rotas_saudaveis")
        if rotas is not None:
            if saudaveis == 0:
                linhas.append(
                    "o que agora: nenhuma rota de IA respondeu. Verificar conexao ou "
                    "as cotas do pool gratuito."
                )
            elif saudaveis < max(2, rotas // 3):
                linhas.append(
                    f"o que agora: so {saudaveis} de {rotas} rotas saudaveis. "
                    "O pool esta degradado; esperar o cooldown dos gateways."
                )
            else:
                linhas.append(f"o que agora: nada. {saudaveis} de {rotas} rotas saudaveis.")
    else:
        linhas.append("o que agora: nada bloqueante registrado.")

    return linhas


def formatar_painel_geral(
    resumo: dict[str, Any], ai: dict[str, Any] | None = None
) -> str:
    """Painel em texto, para `main.py --painel` e para o log do Actions."""
    linhas = ["", "=== painel do Atlas ===", ""]
    linhas += [f"  {l}" for l in responder_as_tres_perguntas(resumo, ai)]

    if ai:
        linhas.append("")
        linhas.append("  --- pool de IA ---")
        for chave in ("gateways", "rotas", "rotas_saudaveis", "chamadas", "fallbacks",
                      "latencia_media_ms", "erros"):
            if chave in ai:
                linhas.append(f"  {chave:<20} {ai[chave]}")

    linhas.append("")
    return "\n".join(linhas)
