"""Casos 16, 19 e 20: falhas externas, e a verificacao pos-acao."""

from __future__ import annotations

import pytest

from atlas.embeds import EmbedKind
from atlas.errors import GatewayError, AIError, PermissionError_
from atlas.ai import FailingModelClient, ModelTurn, ScriptedModelClient
from atlas.models import Perm

from conftest import IDS, final, turn


# --------------------------------------------------------------------- caso 16
def test_16_bot_sem_permissao_do_discord(harness):
    h = harness([turn(("create_channel", {"name": "x", "type": "text"})), final("x")], seed=False)
    h.gateway.bot_permissions &= ~int(Perm.MANAGE_CHANNELS)  # tira a permissao
    h.ctx.snapshot = h.gateway.snapshot()

    outcome = h.ask("cria um canal")

    assert outcome.results[0].ok is False
    assert outcome.results[0].error_kind == "PermissionError_"
    assert h.find_channel_id("x") is None
    assert "MANAGE_CHANNELS" in (outcome.results[0].error or "")


def test_16b_bot_sem_permissao_para_cargos(harness):
    h = harness([turn(("create_role", {"name": "x"})), final("x")], seed=False)
    h.gateway.bot_permissions &= ~int(Perm.MANAGE_ROLES)
    h.ctx.snapshot = h.gateway.snapshot()

    outcome = h.ask("cria um cargo")
    assert outcome.results[0].ok is False
    assert outcome.results[0].error_kind == "PermissionError_"


def test_16c_discord_retorna_forbidden(harness):
    """Simula HTTP 403 vindo da API."""
    h = harness([turn(("create_category", {"name": "NOVO"})), final("x")], seed=False)
    h.gateway.fail_on("create_category", "Missing Permissions")

    outcome = h.ask("cria categoria")
    assert outcome.results[0].ok is False
    assert outcome.results[0].error_kind == "GatewayError"
    assert any(e.kind == EmbedKind.ERROR for e in outcome.embeds)


# --------------------------------------------------------------------- caso 19
def test_19_erro_da_camada_de_ia(harness):
    h = harness([], seed=False)
    h.agent.model = FailingModelClient("429 quota excedida")

    outcome = h.ask("monta uma estrutura")

    assert outcome.results == [], "nada deveria ter sido executado"
    assert len(outcome.embeds) == 1
    assert outcome.embeds[0].kind == EmbedKind.ERROR
    assert "modelo" in outcome.embeds[0].description.lower() or "IA" in outcome.embeds[0].description
    assert any(r["action"] == "ai.error" for r in h.audit.records)


def test_19b_ia_falha_no_meio_do_laco(harness):
    """Primeiro turno ok, segundo falha: o que ja foi feito fica relatado."""
    script = [turn(("create_category", {"name": "PARCIAL"}))]
    h = harness(script, seed=False)
    original = h.agent.model.generate
    calls = {"n": 0}

    def flaky(*, system, history, tools):
        calls["n"] += 1
        if calls["n"] == 1:
            return original(system=system, history=history, tools=tools)
        raise AIError("timeout", user_message="O modelo caiu no meio do caminho.")

    h.agent.model.generate = flaky
    outcome = h.ask("faz algo")

    assert h.find_category_id("PARCIAL") is not None, "a primeira acao deveria ter valido"
    assert any(e.kind == EmbedKind.ERROR for e in outcome.embeds)


# --------------------------------------------------------------------- caso 20
@pytest.mark.parametrize(
    "metodo,tool,args",
    [
        ("create_channel", "create_channel", {"name": "a", "type": "text"}),
        ("create_role", "create_role", {"name": "a"}),
        ("edit_server", "edit_server", {"name": "Novo Nome"}),
        ("create_category", "create_category", {"name": "CAT"}),
    ],
)
def test_20_erro_da_api_discord(harness, metodo, tool, args):
    h = harness([turn((tool, args)), final("x")], seed=False)
    h.gateway.fail_on(metodo, "500 Internal Server Error")

    outcome = h.ask("faz ai")
    assert outcome.results[0].ok is False
    assert outcome.results[0].error_kind == "GatewayError"
    assert any(e.kind == EmbedKind.ERROR for e in outcome.embeds)


def test_20b_erro_do_discord_nao_derruba_o_agente(harness):
    """Um erro numa acao nao pode impedir as seguintes nem estourar excecao."""
    h = harness([
        turn(("create_channel", {"name": "falha", "type": "text"})),
        turn(("create_channel", {"name": "sucesso", "type": "text"})),
        final("ok"),
    ], seed=False)
    h.gateway.fail_on("create_channel", "boom")

    outcome = h.ask("cria dois canais")
    assert len(outcome.results) == 2
    assert outcome.results[0].ok is False
    assert outcome.results[1].ok is True
    assert h.find_channel_id("sucesso") is not None


# --------------------------------------------------------- verificacao pos-acao
def test_verificacao_detecta_mudanca_que_nao_aconteceu(harness):
    """Se a API diz ok mas o estado nao mudou, o agente nao pode afirmar que funcionou."""
    h = harness([turn(("create_category", {"name": "FANTASMA"})), final("x")], seed=False)

    real_create = h.gateway.create_category

    def lying_create(*, name, position=None):
        channel = real_create(name=name, position=position)
        del h.gateway.channels[channel.id]  # some logo depois, simulando inconsistencia
        return channel

    h.gateway.create_category = lying_create
    outcome = h.ask("cria categoria fantasma")

    result = outcome.results[0]
    assert result.ok is True, "a chamada em si nao deu erro"
    assert result.verified is False, "a verificacao deveria ter flagrado"
    assert result.user_message and "nao" in result.user_message.lower()
    kinds = {e.kind for e in outcome.embeds}
    assert EmbedKind.WARNING in kinds or EmbedKind.ERROR in kinds


def test_leitura_antes_de_escrever_usa_estado_fresco(harness):
    h = harness([turn(("get_server_info", {})), final("ok")], seed=False)
    h.ask("como esta o servidor")
    methods = [m for m, _ in h.gateway.calls]
    assert "snapshot" in methods, "o agente deveria ter consultado o estado real"
