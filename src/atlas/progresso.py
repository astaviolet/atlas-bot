"""Progresso da execução (spec 156) e cancelamento seguro (spec 90, 158).

POR QUE O PROGRESSO VAI NA RESPOSTA ÚNICA, E NÃO EM MENSAGENS SEPARADAS
----------------------------------------------------------------------
A spec 156 mostra um exemplo de progresso em Components V2 sendo atualizado
durante a execução. Mas há uma restrição do produto que vale mais: o usuário
exige exatamente UMA mensagem por resposta, sempre. Mensagens de progresso
soltas violariam isso.

O que satisfaz os dois: a resposta única carrega o detalhamento por tipo —
"Categorias: 5/5, Canais: 16/18". Em operação parcial isso não é enfeite, é a
informação que faltava: o usuário precisa saber que 2 de 18 não foram, e não
inferir contando linhas.

Progresso em tempo real por edição de mensagem ficaria disponível se o bot
passar um callback de send/edit para o agente. Não foi feito de propósito: o
`agent.handle` roda em thread via `run_in_executor`, e mandar mensagem async a
partir de thread sync é exatamente o tipo de acoplamento que quebra silencioso.
Está anotado como pendência, não como concluído (spec 185).
"""

from __future__ import annotations

import threading
from typing import Any, Sequence

#: ferramenta → rótulo do progresso, na ordem em que aparecem no resumo
_ROTULOS: dict[str, str] = {
    "create_category": "Categorias",
    "create_channel": "Canais",
    "create_role": "Cargos",
    "edit_channel": "Canais alterados",
    "edit_category": "Categorias alteradas",
    "edit_role": "Cargos alterados",
    "move_channel": "Canais movidos",
    "move_role": "Cargos movidos",
    "set_channel_permissions": "Permissões de canal",
    "set_role_permissions": "Permissões de cargo",
    "delete_channel": "Canais removidos",
    "delete_category": "Categorias removidas",
    "delete_role": "Cargos removidos",
    "reorder_channels": "Ordem dos canais",
    "edit_server": "Servidor",
}

_ORDEM = list(_ROTULOS)


class Progresso:
    """Conta o que foi feito por tipo. Nunca levanta."""

    def __init__(self, acoes: Sequence[Any]) -> None:
        self.total: dict[str, int] = {}
        for a in acoes:
            tool = getattr(a, "tool", "") or ""
            if tool in _ROTULOS:
                self.total[tool] = self.total.get(tool, 0) + 1

    @property
    def total_acoes(self) -> int:
        return sum(self.total.values())

    def linhas(self, resultados: Sequence[Any]) -> list[str]:
        """'Canais: 16/18'. Só tipos que o plano de fato incluía."""
        feitos: dict[str, int] = {}
        for r in resultados:
            if not getattr(r, "ok", False):
                continue
            tool = getattr(getattr(r, "action", None), "tool", "") or ""
            if tool in _ROTULOS:
                feitos[tool] = feitos.get(tool, 0) + 1

        saida = []
        for tool in _ORDEM:
            if tool not in self.total:
                continue
            total = self.total[tool]
            feito = feitos.get(tool, 0)
            marca = "" if feito == total else "  ← incompleto"
            saida.append(f"{_ROTULOS[tool]}: {feito}/{total}{marca}")
        return saida


class Cancelador:
    """Cancelamento cooperativo por guild (spec 90, 158).

    Cooperativo de propósito: o executor pergunta entre uma ação e outra, nunca
    no meio de uma chamada à API do Discord. Interromper uma chamada no meio é o
    que deixa estado parcialmente corrompido sem registro — exatamente o que a
    spec 158 proíbe.

    Um `threading.Event` por guild, e não um flag global: cancelar o servidor A
    não pode cancelar o B (spec 8, isolamento).
    """

    def __init__(self) -> None:
        self._eventos: dict[int, threading.Event] = {}
        self._trava = threading.Lock()

    def _evento(self, guild_id: int) -> threading.Event:
        with self._trava:
            return self._eventos.setdefault(int(guild_id), threading.Event())

    def pedir(self, guild_id: int) -> None:
        self._evento(guild_id).set()

    def cancelado(self, guild_id: int) -> bool:
        return self._evento(guild_id).is_set()

    def limpar(self, guild_id: int) -> None:
        """Começa tarefa nova limpa: pedido antigo não pode matar pedido novo."""
        self._evento(guild_id).clear()

    def ocupados(self) -> list[int]:
        with self._trava:
            return [g for g, e in self._eventos.items() if e.is_set()]
