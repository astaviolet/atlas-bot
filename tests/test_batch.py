"""Caso 10: operacao em lote, e o fluxo de confirmacao para operacoes destrutivas."""

from __future__ import annotations

from atlas.embeds import EmbedKind

from conftest import IDS, final, turn


def test_10_estrutura_completa_em_lote(harness):
    h = harness([
        turn(("create_category", {"name": "SUPORTE"})),
        turn(("create_category", {"name": "STAFF"})),
        turn(("create_channel", {"name": "tickets", "type": "text", "category_id": "__CAT__"})),
        final("Estrutura montada."),
    ], seed=False)

    # o id da categoria SUPORTE so existe depois do primeiro turno
    original = h.model.generate

    def generate(**kwargs):
        result = original(**kwargs)
        for call in result.calls:
            if call.args.get("category_id") == "__CAT__":
                call.args["category_id"] = str(h.find_category_id("SUPORTE"))
        return result

    h.model.generate = generate
    outcome = h.ask("monta uma estrutura de suporte e staff")

    assert h.find_category_id("SUPORTE") is not None
    assert h.find_category_id("STAFF") is not None
    tickets = h.find_channel_id("tickets")
    assert tickets is not None
    assert h.gateway.channels[tickets].parent_id == h.find_category_id("SUPORTE")

    assert all(r.ok for r in outcome.results)
    assert all(r.verified for r in outcome.results), "toda acao de lote precisa ser verificada"
    assert outcome.embeds[0].kind == EmbedKind.SUCCESS


def test_10b_lote_com_falha_parcial_reporta_o_que_falhou(harness):
    h = harness([
        turn(("create_category", {"name": "OK"})),
        turn(
            ("create_channel", {"name": "bom", "type": "text"}),
            ("create_channel", {"name": "ruim", "type": "text", "category_id": "999999999"}),
        ),
        final("Parcial."),
    ], seed=False)
    outcome = h.ask("cria categoria e dois canais")

    ok = [r for r in outcome.results if r.ok]
    failed = [r for r in outcome.results if not r.ok]
    assert len(ok) == 2 and len(failed) == 1
    assert failed[0].action.tool == "create_channel"
    assert h.find_channel_id("bom") is not None
    assert h.find_channel_id("ruim") is None

    kinds = {e.kind for e in outcome.embeds}
    assert EmbedKind.ERROR in kinds or EmbedKind.RESULT in kinds, "a falha precisa aparecer no embed"


def test_10c_lote_grande_respeita_a_cota(harness):
    """40 criacoes passam; 41 nao."""
    calls = [("create_channel", {"name": f"c{i}", "type": "text"}) for i in range(40)]
    h = harness([turn(*calls), final("ok")], seed=False)
    outcome = h.ask("cria 40 canais")
    assert len([r for r in outcome.results if r.ok]) == 40

    calls = [("create_channel", {"name": f"d{i}", "type": "text"}) for i in range(41)]
    h2 = harness([turn(*calls), final("ok")], seed=False)
    outcome2 = h2.ask("cria 41 canais")
    assert outcome2.results == []


def test_exclusao_multipla_exige_confirmacao(harness):
    alvos = [
        IDS["ch_regras_%d" % IDS["cat_informacoes"]],
        IDS["ch_anuncios_%d" % IDS["cat_informacoes"]],
        IDS["ch_regras_%d" % IDS["cat_comunidade"]],
    ]
    h = harness([
        turn(*[("delete_channel", {"channel_id": str(a)}) for a in alvos]),
        final("apagado"),
    ])
    outcome = h.ask("apaga esses tres canais")

    assert outcome.blocked == "confirmation_required", "deveria ter parado para confirmar"
    assert outcome.results == [], "nada deveria ter sido executado antes da confirmacao"
    for alvo in alvos:
        assert alvo in h.gateway.channels, "canal apagado sem confirmacao"
    assert outcome.embeds[0].kind == EmbedKind.CONFIRM

    # usuario confirma
    confirmado = h.ask("sim")
    assert confirmado.blocked is None
    for alvo in alvos:
        assert alvo not in h.gateway.channels, "depois do 'sim' deveria ter apagado"


def test_confirmacao_negativa_cancela(harness):
    alvos = [
        IDS["ch_regras_%d" % IDS["cat_informacoes"]],
        IDS["ch_anuncios_%d" % IDS["cat_informacoes"]],
        IDS["ch_regras_%d" % IDS["cat_comunidade"]],
    ]
    h = harness([
        turn(*[("delete_channel", {"channel_id": str(a)}) for a in alvos]),
        final("apagado"),
    ])
    h.ask("apaga esses tres")
    outcome = h.ask("nao")

    assert outcome.blocked is None
    for alvo in alvos:
        assert alvo in h.gateway.channels, "cancelar deveria preservar tudo"


def test_confirmacao_ambigua_nao_executa(harness):
    alvos = [
        IDS["ch_regras_%d" % IDS["cat_informacoes"]],
        IDS["ch_anuncios_%d" % IDS["cat_informacoes"]],
        IDS["ch_regras_%d" % IDS["cat_comunidade"]],
    ]
    h = harness([
        turn(*[("delete_channel", {"channel_id": str(a)}) for a in alvos]),
        final("apagado"),
    ])
    h.ask("apaga esses tres")
    outcome = h.ask("hum, talvez?")

    assert outcome.blocked == "awaiting_confirmation"
    for alvo in alvos:
        assert alvo in h.gateway.channels


def test_memoria_de_contexto_entre_mensagens(harness):
    """'Crie Moderador' -> 'agora de permissao a ele'."""
    h = harness([
        turn(("create_role", {"name": "Moderador"})),
        final("Cargo criado."),
    ], seed=False)
    h.ask("cria um cargo Moderador")
    rid = h.find_role_id("Moderador")
    assert rid is not None

    h2 = harness(
        [turn(("set_role_permissions", {"role_id": str(rid), "allow": ["manage_channels"]})), final("feito")],
        gateway=h.gateway, seed=False,
    )
    h2.session = h.session  # mesma sessao = mesma memoria
    outcome = h2.ask("agora da pra ele permissao de gerenciar canais")

    assert outcome.results[0].ok is True
    assert h.gateway.roles[rid].permissions & 16  # MANAGE_CHANNELS
    assert h.session.recall("role", "Moderador") == str(rid)
