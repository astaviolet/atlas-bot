"""Fase 5: validador de plano + QA pos-execucao (spec 24, 25, 47, 138)."""

from __future__ import annotations

from conftest import final, turn

from atlas.design_check import auditar_servidor, checar_plano
from atlas.models import Channel, ChannelType, GuildSnapshot, Perm


class Acao:
    def __init__(self, tool, **params):
        self.tool = tool
        self.params = params


def _snap(canais=None, cargos=None):
    base = [Channel(id=1, name="geral", type=ChannelType.GUILD_TEXT)]
    return GuildSnapshot(
        id=1, name="S", owner_id=1, bot_role_id=2, bot_permissions=0,
        channels=base + (canais or []), roles=cargos or [],
    )


# ------------------------------------------------------- validador pre-execucao
def test_cargo_novo_com_administrador_para_o_plano():
    problemas = checar_plano(
        [Acao("create_role", name="Decorativo", permissions=Perm.ADMINISTRATOR.value)],
        _snap(),
    )
    assert problemas and "administrativa" in problemas[0]


def test_cargo_normal_passa():
    assert checar_plano([Acao("create_role", name="Azul", color=0x3498DB)], _snap()) == []


def test_canal_orfao_NAO_para_o_plano():
    """Spec 22/23: sucesso parcial e obrigatorio. Se a acao 7 falha, 1-6 ficam
    feitas e o usuario recebe o relatorio. Rejeitar tudo antes destruia isso -
    foi o erro da primeira versao, e test_10b pegou."""
    assert checar_plano(
        [Acao("create_channel", name="x", type="text", category_id="999999999")], _snap()
    ) == []


def test_duplicata_com_o_servidor_NAO_para_o_plano():
    """A Fase 3 reusa e devolve reused=True. Rejeitar viraria erro duro."""
    snap = _snap(canais=[Channel(id=5, name="COMUNIDADE", type=ChannelType.GUILD_CATEGORY)])
    assert checar_plano([Acao("create_category", name="comunidade")], snap) == []


def test_validador_nunca_estoura_com_parametros_lixo():
    """Validador quebrado nao pode virar outage."""
    lixo = [
        Acao("create_channel", name=None, type="nao-existe", category_id="abc"),
        Acao("create_role", name=None, permissions="muito"),
        Acao("create_channel"),
        Acao("nada"),
    ]
    assert checar_plano(lixo, _snap()) == []  # nao levanta


# ------------------------------------------------------------ QA pos-execucao
def test_qa_aponta_categoria_vazia():
    snap = _snap(canais=[Channel(id=9, name="VAZIA", type=ChannelType.GUILD_CATEGORY)])
    assert any("vazia" in p for p in auditar_servidor(snap))


def test_qa_aponta_canal_duplicado_na_mesma_categoria():
    snap = _snap(canais=[
        Channel(id=2, name="regras", type=ChannelType.GUILD_TEXT, parent_id=9),
        Channel(id=3, name="regras", type=ChannelType.GUILD_TEXT, parent_id=9),
        Channel(id=9, name="INFO", type=ChannelType.GUILD_CATEGORY),
    ])
    assert any("dois canais" in p for p in auditar_servidor(snap))


def test_qa_nao_confunde_mesmo_nome_em_categorias_diferentes():
    snap = _snap(canais=[
        Channel(id=8, name="A", type=ChannelType.GUILD_CATEGORY),
        Channel(id=9, name="B", type=ChannelType.GUILD_CATEGORY),
        Channel(id=2, name="regras", type=ChannelType.GUILD_TEXT, parent_id=8),
        Channel(id=3, name="regras", type=ChannelType.GUILD_TEXT, parent_id=9),
    ])
    assert auditar_servidor(snap) == []


def test_qa_aponta_categoria_duplicada():
    snap = _snap(canais=[
        Channel(id=8, name="INFO", type=ChannelType.GUILD_CATEGORY),
        Channel(id=9, name="info", type=ChannelType.GUILD_CATEGORY),
    ])
    assert any("categorias com o nome" in p for p in auditar_servidor(snap))


# ------------------------------------------------------------- de ponta a ponta
def test_cargo_com_admin_e_bloqueado_antes_de_tocar_o_discord(harness):
    """O plano morre no Executor; nenhuma chamada sai."""
    h = harness([
        turn(("create_role", {"name": "Decorativo", "permissions": str(Perm.ADMINISTRATOR.value)})),
        final("tentei"),
    ], seed=False)
    out = h.ask("cria um cargo decorativo com admin")

    # plano rejeitado = nada executou, entao nem ActionResult existe
    assert out.results == [], out.results
    assert not any(r.name == "Decorativo" for r in h.gateway.snapshot().roles)
    assert out.embeds, "tem que explicar, nao ficar em silencio"
    texto = " ".join(e.description or "" for e in out.embeds)
    assert "administrativa" in texto, texto


def test_qa_aparece_so_em_construcao_grande(harness):
    """Criar UMA categoria e por canais depois e fluxo normal, nao defeito."""
    h = harness([turn(("create_category", {"name": "Staff"})), final("ok")])
    out = h.ask("cria categoria Staff")
    assert not any("vazia" in (e.description or "") for e in out.embeds)


# ------------------------------------------------ Fase 6: dry run (spec 11/12/133)
def test_dry_run_agrupa_por_verbo_e_tipo():
    from atlas.executor import PreparedPlan
    from atlas.executor import PlannedAction

    acoes = [
        PlannedAction(tool="create_category", params={"name": "A"}),
        PlannedAction(tool="create_category", params={"name": "B"}),
        PlannedAction(tool="create_channel", params={"name": "x"}),
        PlannedAction(tool="create_role", params={"name": "R"}),
        PlannedAction(tool="edit_channel", params={"channel_id": "1"}),
        PlannedAction(tool="delete_channel", params={"channel_id": "2"}),
    ]
    plano = PreparedPlan(actions=acoes, token="t", counts={})
    seco = plano.dry_run()

    assert "2 criar categoria" in seco
    assert "1 criar canal" in seco
    assert "1 criar cargo" in seco
    assert "1 remover canal" in seco
    assert "1 alterar canal" in seco


def test_construcao_grande_pede_confirmacao(harness):
    """Spec 12: montar o servidor inteiro tem que mostrar o plano antes."""
    import dataclasses

    muitas = [("create_channel", {"name": f"c{i}", "type": "text"}) for i in range(16)]
    h = harness([turn(*muitas), final("ok")], seed=False)
    novos = dataclasses.replace(h.limits, build_confirm_threshold=15)
    h.limits = novos
    h.ctx.limits = novos  # o Executor le do ctx, nao do harness

    out = h.ask("monta o servidor")
    assert out.blocked == "confirmation_required", out.blocked
    assert h.session.pending is not None
    assert "16 criar canal" in h.session.pending.summary, h.session.pending.summary


def test_construcao_pequena_nao_pede_confirmacao(harness):
    h = harness([
        turn(("create_channel", {"name": "a", "type": "text"}),
             ("create_channel", {"name": "b", "type": "text"})),
        final("ok"),
    ], seed=False)
    out = h.ask("cria dois canais")
    assert out.blocked is None, out.blocked
    assert h.find_channel_id("a") is not None


# ------------------------------------------------ Fase 7: estado da tarefa (spec 22/89/113)
class _R:
    def __init__(self, ok):
        self.ok = ok


def test_estado_da_tarefa_cobre_os_casos():
    from atlas.task import TaskState, estado_da_tarefa

    assert estado_da_tarefa([_R(True), _R(True)]) == TaskState.COMPLETED
    assert estado_da_tarefa([_R(True), _R(False)]) == TaskState.PARTIAL
    assert estado_da_tarefa([_R(False)]) == TaskState.FAILED
    assert estado_da_tarefa([]) == TaskState.NOTHING_TO_DO
    assert estado_da_tarefa([], "confirmation_required") == TaskState.AWAITING_CONFIRMATION
    assert estado_da_tarefa([], "guild_busy") == TaskState.REJECTED
    assert estado_da_tarefa([], "confirmation_expired") == TaskState.CANCELLED
    assert estado_da_tarefa([], "prompt_injection") == TaskState.REJECTED


def test_resumo_da_tarefa_diz_a_conta():
    from atlas.task import resumo_da_tarefa

    assert resumo_da_tarefa([_R(True)] * 16) == "16 concluida(s)"
    r = resumo_da_tarefa([_R(True)] * 16 + [_R(False)] * 2)
    assert "16" in r and "2" in r and "nao foi tudo" in r
    assert "nenhuma concluida" in resumo_da_tarefa([_R(False), _R(False)])


def test_falha_parcial_aparece_no_resultado(harness):
    """Spec 22: 2 de 3 nao pode virar 'tudo pronto'."""
    from atlas.task import TaskState

    h = harness([
        turn(("create_category", {"name": "OK"})),
        turn(("create_channel", {"name": "bom", "type": "text"}),
             ("create_channel", {"name": "ruim", "type": "text", "category_id": "999999999"})),
        final("Parcial."),
    ], seed=False)
    out = h.ask("cria categoria e dois canais")

    assert out.state == TaskState.PARTIAL, out.state
    textos = " ".join(e.description or "" for e in out.embeds)
    assert "nao foi tudo" in textos, textos


# ------------------------------------------------- spec 138: real vs planejado
def _arq_de_teste():
    from atlas.design_system import Briefing, Dominio, Porte, projetar

    return projetar(Briefing(dominio=Dominio.GAMING_COMPETITIVO, porte=Porte.MEDIO))


def test_conferir_aponta_area_que_faltou():
    from atlas.design_check import conferir_contra_design
    from atlas.models import Channel, ChannelType, GuildSnapshot

    arq = _arq_de_teste()
    # servidor com só uma das áreas
    snap = GuildSnapshot(
        id=1, name="S", owner_id=1, bot_role_id=9, bot_permissions=0,
        channels=[Channel(id=1, name=arq.categorias[0].nome, type=ChannelType.GUILD_CATEGORY)],
    )
    faltas = conferir_contra_design(snap, arq)
    assert faltas, "tinha que apontar o que falta"
    assert any("não foi criada" in f for f in faltas)


def test_conferir_aponta_canal_que_faltou():
    from atlas.design_check import conferir_contra_design
    from atlas.models import Channel, ChannelType, GuildSnapshot

    arq = _arq_de_teste()
    chans = []
    for i, cat in enumerate(arq.categorias):
        chans.append(Channel(id=100 + i, name=cat.nome, type=ChannelType.GUILD_CATEGORY))
    snap = GuildSnapshot(id=1, name="S", owner_id=1, bot_role_id=9,
                         bot_permissions=0, channels=chans)
    faltas = conferir_contra_design(snap, arq)
    assert any("não foi criado" in f for f in faltas)


def test_conferir_nao_reclama_quando_tudo_foi_feito():
    from atlas.design_check import conferir_contra_design
    from atlas.models import Channel, ChannelType, GuildSnapshot

    arq = _arq_de_teste()
    chans, n = [], 100
    for cat in arq.categorias:
        n += 1
        chans.append(Channel(id=n, name=cat.nome, type=ChannelType.GUILD_CATEGORY))
        for c in cat.canais:
            n += 1
            chans.append(Channel(id=n, name=c.nome, type=ChannelType.GUILD_TEXT, parent_id=n - 1))
    snap = GuildSnapshot(id=1, name="S", owner_id=1, bot_role_id=9,
                         bot_permissions=0, channels=chans)
    assert conferir_contra_design(snap, arq) == []


def test_conferir_nao_aponta_excesso():
    """Canal a mais pode ser do proprio servidor - a reforma preserva o que
    existe (spec 46). Apontar excesso seria alarme falso em toda reforma."""
    from atlas.design_check import conferir_contra_design
    from atlas.models import Channel, ChannelType, GuildSnapshot

    arq = _arq_de_teste()
    chans, n = [], 100
    for cat in arq.categorias:
        n += 1
        chans.append(Channel(id=n, name=cat.nome, type=ChannelType.GUILD_CATEGORY))
        for c in cat.canais:
            n += 1
            chans.append(Channel(id=n, name=c.nome, type=ChannelType.GUILD_TEXT, parent_id=n - 1))
    chans.append(Channel(id=999, name="canal-que-ja-existia", type=ChannelType.GUILD_TEXT))
    snap = GuildSnapshot(id=1, name="S", owner_id=1, bot_role_id=9,
                         bot_permissions=0, channels=chans)
    assert conferir_contra_design(snap, arq) == []


def test_conferir_sem_arquitetura_nao_estoura():
    from atlas.design_check import conferir_contra_design
    from atlas.models import GuildSnapshot

    snap = GuildSnapshot(id=1, name="S", owner_id=1, bot_role_id=9, bot_permissions=0)
    assert conferir_contra_design(snap, None) == []


def test_conferir_ignora_caixa_e_separador():
    """'「🏆」competitivo' tem que casar com 'competitivo', senao a verificacao
    reclama de coisa que foi feita."""
    from atlas.design_check import conferir_contra_design
    from atlas.design_system import (
        Briefing, Dominio, EstiloVisual, Porte, projetar,
    )
    from atlas.models import Channel, ChannelType, GuildSnapshot

    arq = projetar(Briefing(dominio=Dominio.GAMING_COMPETITIVO, porte=Porte.PEQUENO,
                            estilo=EstiloVisual.COMPETITIVO))
    chans, n = [], 100
    for cat in arq.categorias:
        n += 1
        chans.append(Channel(id=n, name=cat.nome.upper(), type=ChannelType.GUILD_CATEGORY))
        for c in cat.canais:
            n += 1
            chans.append(Channel(id=n, name=c.nome, type=ChannelType.GUILD_TEXT, parent_id=n - 1))
    snap = GuildSnapshot(id=1, name="S", owner_id=1, bot_role_id=9,
                         bot_permissions=0, channels=chans)
    assert conferir_contra_design(snap, arq) == []
