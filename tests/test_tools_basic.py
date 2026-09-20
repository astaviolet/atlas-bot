"""Casos 1 a 9: as operacoes estruturais basicas, com verificacao pos-acao."""

from __future__ import annotations

import pytest

from atlas.embeds import EmbedKind
from atlas.models import ChannelType

from conftest import IDS, final, turn


def test_01_criar_canal(harness):
    h = harness([
        turn(("create_channel", {"name": "avisos", "type": "text", "category_id": str(IDS["cat_informacoes"])})),
        final("Canal criado."),
    ])
    outcome = h.ask("cria um canal de avisos dentro de INFORMACOES")

    cid = h.find_channel_id("avisos")
    assert cid is not None, "o canal nao foi criado"
    assert h.gateway.channels[cid].parent_id == IDS["cat_informacoes"]
    assert h.gateway.channels[cid].type == ChannelType.GUILD_TEXT

    assert len(outcome.results) == 1
    assert outcome.results[0].ok is True
    assert outcome.results[0].verified is True, "a verificacao pos-acao falhou"
    assert outcome.embeds[0].kind == EmbedKind.SUCCESS


def test_01b_criar_canal_de_voz_e_forum(harness):
    h = harness([
        turn(
            ("create_channel", {"name": "Sala AFK", "type": "voice", "category_id": str(IDS["cat_voz"])}),
            ("create_channel", {"name": "duvidas", "type": "forum"}),
        ),
        final("Feito."),
    ])
    outcome = h.ask("cria uma sala de voz e um forum")

    voice = h.find_channel_id("Sala AFK")
    forum = h.find_channel_id("duvidas")
    assert voice and h.gateway.channels[voice].type == ChannelType.GUILD_VOICE
    assert forum and h.gateway.channels[forum].type == ChannelType.GUILD_FORUM
    assert all(r.ok for r in outcome.results)


def test_02_criar_categoria(harness):
    h = harness([
        turn(("create_category", {"name": "eventos"})),
        final("Categoria criada."),
    ])
    outcome = h.ask("cria uma categoria de eventos")

    cid = h.find_category_id("EVENTOS")
    assert cid is not None, "categoria nao criada"
    assert h.gateway.channels[cid].is_category is True
    assert outcome.results[0].verified is True


def test_03_criar_cargo(harness):
    h = harness([
        turn(("create_role", {"name": "Moderador", "color": "#5865F2", "hoist": True})),
        final("Cargo criado."),
    ])
    outcome = h.ask("cria um cargo Moderador azul")

    rid = h.find_role_id("Moderador")
    assert rid is not None
    role = h.gateway.roles[rid]
    assert role.color == 0x5865F2
    assert role.hoist is True
    assert outcome.results[0].verified is True


def test_06_reorganizar_canais(harness):
    alvo = IDS["ch_regras_%d" % IDS["cat_comunidade"]]
    h = harness([
        turn(("move_channel", {"channel_id": str(alvo), "category_id": str(IDS["cat_informacoes"])})),
        turn(("reorder_channels", {"items": [{"id": str(alvo), "position": 9}]})),
        final("Reorganizado."),
    ])
    outcome = h.ask("move regras para INFORMACOES e joga para o fim")

    channel = h.gateway.channels[alvo]
    assert channel.parent_id == IDS["cat_informacoes"], "canal nao foi movido"
    assert channel.position == 9, "posicao nao aplicada"
    assert all(r.ok for r in outcome.results)
    assert all(r.verified for r in outcome.results)


def test_07_alterar_nome_do_servidor(harness):
    h = harness([
        turn(("edit_server", {"name": "Comunidade Atlas"})),
        final("Nome alterado."),
    ])
    outcome = h.ask("muda o nome do servidor para Comunidade Atlas")

    assert h.gateway.name == "Comunidade Atlas"
    assert outcome.results[0].verified is True


def test_08_alterar_configuracoes_suportadas(harness):
    h = harness([
        turn(("edit_server", {"description": "Servidor de testes do agente Atlas"})),
        final("Descricao atualizada."),
    ])
    outcome = h.ask("coloca uma descricao no servidor")

    assert h.gateway.description == "Servidor de testes do agente Atlas"
    assert outcome.results[0].verified is True


def test_08b_configuracao_invalida_e_recusada(harness):
    h = harness([
        turn(("edit_server", {"name": "x"})),
        final("Tentei."),
    ])
    outcome = h.ask("muda o nome para x")

    assert outcome.results[0].ok is False
    assert h.gateway.name != "x"
    assert any(e.kind == EmbedKind.ERROR for e in outcome.embeds)


def test_09_excluir_canal(harness):
    alvo = IDS["ch_anuncios_%d" % IDS["cat_informacoes"]]
    h = harness([
        turn(("delete_channel", {"channel_id": str(alvo)})),
        final("Canal removido."),
    ])
    outcome = h.ask("apaga o canal anuncios de INFORMACOES")

    assert alvo not in h.gateway.channels, "canal ainda existe"
    assert outcome.results[0].ok is True
    assert outcome.results[0].verified is True


# ------------------------------------------------ Fase 3: idempotencia (spec 13/178)
def _contar(h, nome, categoria=False):
    return sum(
        1 for c in h.gateway.channels.values()
        if c.name.casefold() == nome.casefold() and c.is_category == categoria
    )


def test_178_categoria_pedida_duas_vezes_nao_duplica(harness):
    """Spec 178 literal: pedir 'crie categoria comunidade' duas vezes."""
    h = harness([
        turn(("create_category", {"name": "comunidade"})),
        final("criada"),
    ])
    h.ask("crie categoria comunidade")
    assert _contar(h, "comunidade", categoria=True) == 1

    h2 = harness([
        turn(("create_category", {"name": "comunidade"})),
        final("criada"),
    ], gateway=h.gateway, seed=False)
    out = h2.ask("crie categoria comunidade de novo")

    assert _contar(h2, "comunidade", categoria=True) == 1, "criou categoria duplicada"
    assert out.results[0].data.get("reused") is True, "tem que avisar que reusou"


def test_categoria_existente_com_outra_caixa_nao_duplica(harness):
    """Discord guarda categoria em MAIUSCULA; 'comunidade' nao pode virar outra."""
    h = harness([turn(("create_category", {"name": "Staff"})), final("ok")])
    h.ask("cria categoria Staff")
    h2 = harness([turn(("create_category", {"name": "staff"})), final("ok")],
                 gateway=h.gateway, seed=False)
    h2.ask("cria categoria staff")
    assert _contar(h2, "staff", categoria=True) == 1


def test_canal_duplicado_nao_e_criado(harness):
    h = harness([
        turn(("create_channel", {"name": "avisos", "type": "text",
                                 "category_id": str(IDS["cat_informacoes"])})),
        final("ok"),
    ])
    h.ask("cria canal avisos")
    antes = _contar(h, "avisos")

    h2 = harness([
        turn(("create_channel", {"name": "avisos", "type": "text",
                                 "category_id": str(IDS["cat_informacoes"])})),
        final("ok"),
    ], gateway=h.gateway, seed=False)
    out = h2.ask("cria canal avisos de novo")

    assert _contar(h2, "avisos") == antes == 1, "duplicou o canal"
    assert out.results[0].data.get("reused") is True


def test_mesmo_nome_tipo_diferente_cria_os_dois(harness):
    """Guarda contra casamento agressivo: 'geral' texto e 'geral' voz sao dois."""
    h = harness([
        turn(("create_channel", {"name": "geral", "type": "text"}),
             ("create_channel", {"name": "geral", "type": "voice"})),
        final("ok"),
    ])
    h.ask("cria geral de texto e de voz")
    tipos = sorted(c.type for c in h.gateway.channels.values() if c.name == "geral")
    assert tipos == [ChannelType.GUILD_TEXT, ChannelType.GUILD_VOICE], tipos


def test_mesmo_nome_categoria_diferente_cria_os_dois(harness):
    h = harness([
        turn(("create_channel", {"name": "regras", "type": "text",
                                 "category_id": str(IDS["cat_informacoes"])}),
             ("create_channel", {"name": "regras", "type": "text",
                                 "category_id": str(IDS["cat_comunidade"])})),
        final("ok"),
    ])
    h.ask("cria regras nas duas categorias")
    assert _contar(h, "regras") >= 2, "bloqeu nome igual em categorias diferentes"


def test_cargo_duplicado_nao_e_criado(harness):
    h = harness([turn(("create_role", {"name": "Moderador"})), final("ok")], seed=False)
    h.ask("cria cargo Moderador")
    h2 = harness([turn(("create_role", {"name": "moderador"})), final("ok")],
                 gateway=h.gateway, seed=False)
    out = h2.ask("cria cargo moderador")
    nomes = [r.name for r in h2.gateway.snapshot().roles]
    assert nomes.count("Moderador") + nomes.count("moderador") == 1, nomes
    assert out.results[0].data.get("reused") is True


def test_criar_cargo_everyone_e_recusado(harness):
    """@everyone e o cargo padrao: nao se cria outro com o mesmo nome."""
    from atlas.errors import ToolError

    h = harness([], seed=False)
    reg = h.registry
    with pytest.raises(ToolError) as exc:
        reg.get("create_role").handler(h.ctx, {"name": "@everyone"})
    assert "everyone" in exc.value.user_message.lower()
    # nada foi criado: o unico @everyone e o padrao que ja veio com o servidor
    nomes = [r.name for r in h.gateway.snapshot().roles]
    assert nomes.count("@everyone") == 1, nomes
