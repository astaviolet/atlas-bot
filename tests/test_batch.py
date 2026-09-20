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
    """40 criacoes passam depois de confirmadas; 41 a cota barra.

    A Fase 6 mudou o primeiro passo de proposito: construcao grande agora mostra
    o plano e espera o "sim" antes de tocar no Discord (spec 12). O teste antigo
    esperava execucao direta; o fluxo novo e confirmar e so entao executar.
    """
    calls = [("create_channel", {"name": f"c{i}", "type": "text"}) for i in range(40)]
    h = harness([turn(*calls), final("ok")], seed=False)
    pedido = h.ask("cria 40 canais")
    assert pedido.blocked == "confirmation_required", pedido.blocked

    outcome = h.ask("sim")
    assert len([r for r in outcome.results if r.ok]) == 40

    calls = [("create_channel", {"name": f"d{i}", "type": "text"}) for i in range(41)]
    h2 = harness([turn(*calls), final("ok")], seed=False)
    # 41 estoura a cota, e a cota e checada ANTES da confirmacao: recusa na
    # hora, sem nem perguntar. Melhor do que pedir "sim" para algo impossivel.
    outcome2 = h2.ask("cria 41 canais")
    assert outcome2.results == [], "41 passa da cota e nao pode executar nada"
    assert outcome2.blocked is None, "e erro de cota, nao pedido de confirmacao"
    assert any("limite" in (e.description or "") for e in outcome2.embeds)


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


# ------------------------------------------- Fase 2: confirmacao tem prazo
def test_confirmacao_vencida_nao_executa(harness):
    """Spec 177: criar confirmacao, esperar expirar, clicar. Tem que falhar.

    Antes da Fase 2 `session.py` nao tinha nenhuma nocao de tempo: um "sim"
    digitado horas depois executava o plano antigo num servidor que pode ter
    mudado completamente nesse meio tempo.
    """
    alvos = [
        IDS["ch_regras_%d" % IDS["cat_informacoes"]],
        IDS["ch_anuncios_%d" % IDS["cat_informacoes"]],
        IDS["ch_regras_%d" % IDS["cat_comunidade"]],
    ]
    h = harness([
        turn(*[("delete_channel", {"channel_id": str(a)}) for a in alvos]),
        final("apagado"),
    ])
    agora = [1000.0]
    h.session.clock = lambda: agora[0]

    h.ask("apaga esses tres")
    assert h.session.pending is not None, "o teste precisa chegar no pending"

    agora[0] += h.limits.confirmation_ttl_seconds + 1  # passou do prazo
    outcome = h.ask("sim")

    assert outcome.blocked == "confirmation_expired"
    assert h.session.pending is None, "pendencia velha tem que ser descartada"
    for alvo in alvos:
        assert alvo in h.gateway.channels, "confirmacao vencida nao pode apagar nada"


def test_confirmacao_dentro_do_prazo_executa(harness):
    """Guarda contra a correcao virar bloqueio permanente."""
    alvos = [
        IDS["ch_regras_%d" % IDS["cat_informacoes"]],
        IDS["ch_anuncios_%d" % IDS["cat_informacoes"]],
        IDS["ch_regras_%d" % IDS["cat_comunidade"]],
    ]
    h = harness([
        turn(*[("delete_channel", {"channel_id": str(a)}) for a in alvos]),
        final("apagado"),
    ])
    agora = [1000.0]
    h.session.clock = lambda: agora[0]

    h.ask("apaga esses tres")
    agora[0] += 10  # bem dentro do prazo
    h.ask("sim")

    for alvo in alvos:
        assert alvo not in h.gateway.channels, "dentro do prazo tem que executar"


def test_prazo_zero_desliga_a_expiracao(harness):
    import dataclasses

    from atlas.session import PendingConfirmation

    h = harness([])
    h.session.limits = dataclasses.replace(h.limits, confirmation_ttl_seconds=0.0)

    h.session.pending = PendingConfirmation(token="t", calls=[], summary="s", created_at=0.0)
    h.session.clock = lambda: 999_999.0
    assert h.session.confirmacao_vencida() is False


def test_sem_pendencia_nao_esta_vencida(harness):
    h = harness([])
    assert h.session.confirmacao_vencida() is False


# ------------------------------------------------- spec 152: tool result
def test_resultado_carrega_metadata_real(harness):
    """Spec 152 pede success/status/data/error/metadata. metadata nao pode ser
    dict vazio - ai seria campo decorativo so para constar na lista."""
    h = harness([turn(("create_role", {"name": "Moderador"})), final("ok")])
    out = h.ask("cria o cargo Moderador")
    ok = [r for r in out.results if r.ok]
    assert ok, out.results
    md = ok[0].metadata
    assert md["tool"] == "create_role"
    assert isinstance(md["duration_ms"], float) and md["duration_ms"] >= 0
    assert md["guild_id"] == h.gateway.guild_id
    assert "corrigiu" in md


def test_status_e_derivado_nunca_guardado(harness):
    """Se status fosse campo guardado, ele podia divergir de ok. Derivado, nao
    tem como."""
    h = harness([turn(("create_role", {"name": "X"})), final("ok")])
    out = h.ask("cria o cargo X")
    r = out.results[0]
    assert r.status == ("verified" if r.verified else "ok")


def test_status_de_falha_diz_o_tipo_do_erro(harness):
    """Sem o assert de que a falha EXISTE este teste passava vazio - `if falhas`
    sobre lista vazia nao afirma nada."""
    h = harness([turn(("delete_channel", {"channel_id": 999999})), final("ok")])
    out = h.ask("apaga esse canal")
    falhas = [r for r in out.results if not r.ok]
    assert falhas, "apagar canal que nao existe tem que falhar"
    assert falhas[0].status != "ok"
    assert falhas[0].status == (falhas[0].error_kind or "error").lower()
    assert falhas[0].metadata["tool"] == "delete_channel"
