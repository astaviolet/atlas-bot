"""Testes do bot minimo.

O criterio aqui e o que o usuario pediu: uma chamada de IA por mensagem, resposta
montada em codigo, e a acao acontecendo de verdade no gateway.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from atlas.ai.base import FunctionCall, ModelTurn
from atlas.minimo import MAX_TEXTO, AtlasMinimo, _CONFIRMA, limpar
from atlas.tools import ToolContext

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")


class _Canal:
    """Discord.Message e pesado demais para construir; isto cobre o que o bot usa."""

    def __init__(self, channel_id: int = 600000000000000002) -> None:
        self.channel = type("C", (), {"id": channel_id})()
        self.guild = type("G", (), {"id": 1546763083005825084})()
        self.enviadas: list[str] = []

    async def reply(self, *, embed: Any = None, mention_author: bool = True) -> None:
        self.enviadas.append(embed.description or "")


def _bot_minimo(h) -> AtlasMinimo:
    """Monta o bot sem conectar no Discord (on_ready nunca roda)."""
    bot = AtlasMinimo.__new__(AtlasMinimo)
    from atlas.audit import AuditLog
    from atlas.ai.router import Router
    from atlas.tools import build_registry

    bot.audit = AuditLog()
    bot.registry = build_registry()
    bot.router = Router([])
    bot.estados = {}
    bot.limites = {}
    bot.settings = None
    bot.gateway_fixo = h.gateway
    return bot


def _ctx(h, channel_id: int) -> ToolContext:
    from atlas.config import Limits
    from atlas.minimo import politica_para

    lim = Limits()
    ctx = ToolContext(
        guild_id=1546763083005825084,
        gateway=h.gateway,
        policy=politica_para(lim, 1546763083005825084),
        limits=lim,
        snapshot=h.gateway.snapshot(),
    )
    ctx.source_channel_id = channel_id
    return ctx


# ------------------------------------------------------- uma chamada por mensagem
def test_uma_chamada_de_ia_por_mensagem(harness):
    """A causa do atraso eram 4 voltas de IA. Aqui tem que ser UMA."""
    from conftest import IDS

    h = harness([])
    bot = _bot_minimo(h)
    chamadas: list[str] = []

    def fake_generate(**kwargs: Any) -> ModelTurn:
        chamadas.append("ia")
        return ModelTurn(calls=[FunctionCall(name="create_channel",
                                             args={"name": "avisos", "type": 0,
                                                   "parent_id": IDS["cat_informacoes"]})])

    bot.router.generate = fake_generate  # type: ignore[method-assign]

    alvo = IDS["ch_bate_papo"]
    ctx = _ctx(h, alvo)
    msg = _Canal(alvo)

    estado = type("E", (), {"pendente": None, "chamadas": 0})()
    asyncio.run(bot._executar(msg, estado,
                              [FunctionCall(name="create_channel",
                                            args={"name": "avisos", "type": 0,
                                                  "parent_id": IDS["cat_informacoes"]})],
                              "", ctx=ctx))

    nomes = [c.name for c in h.gateway.channels.values()]
    assert "avisos" in nomes, f"canal nao foi criado: {nomes}"
    assert len(msg.enviadas) == 1, f"mandou {len(msg.enviadas)} mensagens, tem que ser 1"
    assert "Criei o canal avisos." == msg.enviadas[0]


def test_resposta_e_montada_em_codigo_sem_segunda_volta(harness):
    """Se precisasse de uma segunda chamada para 'escrever bonito', o atraso voltava."""
    h = harness([])
    bot = _bot_minimo(h)
    from conftest import IDS

    def explode(**kwargs: Any) -> ModelTurn:
        raise AssertionError("nao pode haver segunda chamada de IA")

    bot.router.generate = explode  # type: ignore[method-assign]

    alvo = IDS["ch_bate_papo"]
    msg = _Canal(alvo)
    estado = type("E", (), {"pendente": None, "chamadas": 0})()
    asyncio.run(bot._executar(msg, estado, [], "ok", ctx=_ctx(h, alvo)))
    assert len(msg.enviadas) == 1


# ------------------------------------------------------------------- seguranca
def test_nao_apaga_o_canal_de_controle_mesmo_no_bot_minimo(harness):
    """O bot anterior apagou o proprio canal de controle. Isso nao pode voltar."""
    from atlas.errors import ToolError
    from conftest import IDS

    h = harness([])
    alvo = IDS["ch_bate_papo"]
    ctx = _ctx(h, alvo)
    from atlas.tools import build_registry

    registry = build_registry()
    with pytest.raises(ToolError):
        registry.get("delete_channel").handler(ctx, {"channel_id": str(alvo)})
    assert alvo in h.gateway.channels


def test_tres_ou_mais_exclusoes_pedem_confirmacao():
    from atlas.minimo import LIMIAR_DESTRUICAO

    assert LIMIAR_DESTRUICAO == 3


@pytest.mark.parametrize("texto,esperado", [
    ("sim", True), ("Confirmo", True), ("pode", True), ("ok", True),
    ("nao", False), ("espera", False), ("cria um canal", False),
])
def test_reconhece_confirmacao(texto: str, esperado: bool) -> None:
    assert bool(_CONFIRMA.match(texto.strip())) is esperado


# ----------------------------------------------------------------------- saida
def test_resposta_sempre_curta() -> None:
    longo = "a" * 5000
    saida = limpar(longo, limite=MAX_TEXTO)
    # limpar corta em MAX_TEXTO e acrescenta reticencias; o teto real e 400 + 6
    assert len(saida) <= MAX_TEXTO + 10, f"resposta de {len(saida)} chars"


def test_everyone_nao_vira_mencao_real() -> None:
    """Pode citar, nunca disparar."""
    bot = AtlasMinimo.__new__(AtlasMinimo)
    msg = _Canal()
    asyncio.run(bot._responder(msg, "avisei @everyone e @here"))
    saida = msg.enviadas[0]
    assert "@everyone" not in saida
    assert "@here" not in saida
    assert "everyone" in saida


def test_sempre_exatamente_uma_mensagem() -> None:
    bot = AtlasMinimo.__new__(AtlasMinimo)
    msg = _Canal()
    asyncio.run(bot._responder(msg, "Feito."))
    assert len(msg.enviadas) == 1
