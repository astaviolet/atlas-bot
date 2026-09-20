"""Dependências de execução (spec 21).

O planner pode devolver as ações em qualquer ordem. Executar na ordem que veio
quebra de dois jeitos concretos:

1. "criar canal dentro da categoria X" antes de "criar categoria X" → o canal
   falha porque X ainda não existe.
2. "excluir #antigo" depois de "criar #antigo" → a idempotência da Fase 3 faz o
   create REUTILIZAR o canal existente, e o delete que vem depois apaga justo o
   que acabou de ser reaproveitado. O pedido inteiro se desfaz.

Por isso exclusão vem ANTES de criação: limpa o espaço primeiro. E criação de
categoria antes de canal, porque canal depende de categoria.

A ordenação é ESTÁVEL. Dentro do mesmo nível a ordem do modelo é preservada —
ela define a posição em que os canais aparecem na barra lateral, e reordenar
isso seria mudar o design sem avisar.
"""

from __future__ import annotations

from typing import Any, Sequence

#: nível → ferramentas. Quanto menor o número, antes executa.
_NIVEIS: dict[str, int] = {
    # 0 — leitura. Não muda nada, e o resto pode depender do que ela viu.
    "get_server_info": 0, "get_channels": 0, "get_categories": 0,
    "get_channel": 0, "get_roles": 0, "get_role": 0,
    # 1 — limpar antes de construir (ver docstring, caso 2).
    "delete_category": 1, "delete_channel": 1, "delete_role": 1,
    # 2 — categoria antes de canal: canal depende de categoria.
    "create_category": 2,
    # 3 — o resto das criações.
    "create_channel": 3, "create_role": 3,
    # 4 — mover e editar pressupõe que o alvo existe.
    "move_channel": 4, "move_role": 4,
    "edit_channel": 4, "edit_category": 4, "edit_role": 4,
    # 5 — permissão por último: precisa do canal E do cargo já criados.
    "set_channel_permissions": 5, "set_role_permissions": 5,
    # 6 — ordenação e ajuste do servidor fecham o plano.
    "reorder_channels": 6, "edit_server": 6,
}

#: Ferramenta que não está na tabela vai para cá: executa depois das conhecidas,
#: em vez de furar a fila. Extensibilidade (spec 126) sem quebrar a ordem.
_NIVEL_DESCONHECIDO = 7


def nivel(tool: str) -> int:
    return _NIVEIS.get(str(tool or "").strip().lower(), _NIVEL_DESCONHECIDO)


def ordenar_por_dependencia(actions: Sequence[Any]) -> list[Any]:
    """Ordena estável por nível de dependência. Nunca descarta ação nenhuma."""
    return sorted(actions, key=lambda a: nivel(getattr(a, "tool", "")))


def violacoes(actions: Sequence[Any]) -> list[str]:
    """Aponta dependências que a ordenação não consegue resolver sozinha.

    Hoje só um caso: mover/editar/permissionar um canal que o plano não cria e
    que também não existe. Devolve descrições legíveis, não ids.
    """
    criados = {
        str(getattr(a, "params", {}).get("name", "")).strip().casefold()
        for a in actions
        if getattr(a, "tool", "") in ("create_channel", "create_category")
    }
    problemas = []
    for a in actions:
        tool = getattr(a, "tool", "")
        if tool not in ("move_channel", "set_channel_permissions"):
            continue
        params = getattr(a, "params", {}) or {}
        nome = str(params.get("name", "")).strip().casefold()
        if nome and nome not in criados and "channel_id" not in params:
            problemas.append(f"{tool} mira '{params.get('name')}' que o plano não cria")
    return problemas
