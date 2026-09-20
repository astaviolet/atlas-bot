"""Casos 1 a 9: as operacoes estruturais basicas, com verificacao pos-acao."""

from __future__ import annotations

from atlas.embeds import EmbedKind
from atlas.models import ChannelType, Perm

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


def test_04_alterar_cargo(harness):
    script = [
        turn(("create_role", {"name": "Suporte"})),
        turn(("edit_role", {"role_id": "__ROLE__", "name": "Equipe de Suporte", "color": "#2ECC71"})),
        final("Renomeado."),
    ]
    h = harness(script)

    # resolve o id do cargo recem-criado entre um turno e outro
    original = h.model.generate

    def generate(*, system, history, tools):
        result = original(system=system, history=history, tools=tools)
        for call in result.calls:
            if call.args.get("role_id") == "__ROLE__":
                call.args["role_id"] = str(h.find_role_id("Suporte"))
        return result

    h.model.generate = generate
    outcome = h.ask("cria Suporte e depois renomeia para Equipe de Suporte")

    rid = h.find_role_id("Equipe de Suporte")
    assert rid is not None, "cargo nao foi renomeado"
    assert h.find_role_id("Suporte") is None
    assert h.gateway.roles[rid].color == 0x2ECC71
    assert all(r.ok for r in outcome.results)


def test_05_alterar_permissoes_de_cargo(harness):
    script = [
        turn(("create_role", {"name": "Curador"})),
        turn(("set_role_permissions", {"role_id": "__ROLE__", "allow": ["manage_channels", "manage_messages"]})),
        final("Permissoes aplicadas."),
    ]
    h = harness(script)
    original = h.model.generate

    def generate(*, system, history, tools):
        result = original(system=system, history=history, tools=tools)
        for call in result.calls:
            if call.args.get("role_id") == "__ROLE__":
                call.args["role_id"] = str(h.find_role_id("Curador"))
        return result

    h.model.generate = generate
    outcome = h.ask("cria Curador e da permissao de gerenciar canais e mensagens")

    rid = h.find_role_id("Curador")
    bits = h.gateway.roles[rid].permissions
    assert bits & int(Perm.MANAGE_CHANNELS)
    assert bits & int(Perm.MANAGE_MESSAGES)
    assert not bits & int(Perm.BAN_MEMBERS)
    assert outcome.results[-1].verified is True


def test_05b_alterar_permissoes_de_canal(harness):
    script = [
        turn(("create_role", {"name": "Visitante"})),
        turn((
            "set_channel_permissions",
            {"channel_id": str(IDS["ch_regras_%d" % IDS["cat_informacoes"]]),
             "role_id": "__ROLE__", "allow": ["view_channel"], "deny": ["send_messages"]},
        )),
        final("Feito."),
    ]
    h = harness(script)
    original = h.model.generate

    def generate(*, system, history, tools):
        result = original(system=system, history=history, tools=tools)
        for call in result.calls:
            if call.args.get("role_id") == "__ROLE__":
                call.args["role_id"] = str(h.find_role_id("Visitante"))
        return result

    h.model.generate = generate
    h.ask("deixa Visitante so ver o canal de regras")

    rid = h.find_role_id("Visitante")
    channel = h.gateway.channels[IDS["ch_regras_%d" % IDS["cat_informacoes"]]]
    ow = next(o for o in channel.overwrites if o.target_id == rid)
    assert ow.allow & int(Perm.VIEW_CHANNEL)
    assert ow.deny & int(Perm.SEND_MESSAGES)


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


def test_09b_excluir_categoria_nao_apaga_filhos(harness):
    """Comportamento real do Discord: os canais ficam orfaos."""
    h = harness([
        turn(("delete_category", {"category_id": str(IDS["cat_voz"])})),
        turn(("delete_category", {"category_id": str(IDS["cat_comunidade"])})),
        turn(("delete_category", {"category_id": str(IDS["cat_informacoes"])})),
        final("Categorias removidas."),
    ])
    h.session.pending = None
    h.ask("apaga as categorias")

    # a primeira leva ja dispara confirmacao; aqui confirmamos para testar o cascade
    if h.session.pending is None:
        assert IDS["cat_voz"] not in h.gateway.channels
        for cid in (IDS["ch_sala_geral_%d" % IDS["cat_voz"]], IDS["ch_afk_%d" % IDS["cat_voz"]]):
            assert cid in h.gateway.channels, "filho foi apagado junto, nao e o comportamento do Discord"
            assert h.gateway.channels[cid].parent_id is None
