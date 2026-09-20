"""Progresso (spec 156) e cancelamento seguro (spec 90/158)."""

from __future__ import annotations

from conftest import final, turn

from atlas.embeds import EmbedKind
from atlas.progresso import Cancelador, Progresso
from atlas.queue import ActionQueue, PlannedAction


class _R:
    def __init__(self, tool, ok=True):
        self.ok = ok
        self.action = PlannedAction(tool=tool)


# ------------------------------------------------------------------- progresso
def test_contagem_por_tipo():
    p = Progresso([PlannedAction(tool="create_channel")] * 3
                  + [PlannedAction(tool="create_category")])
    linhas = p.linhas([_R("create_category"), _R("create_channel"), _R("create_channel")])
    assert "Categorias: 1/1" in linhas
    assert any("Canais: 2/3" in l and "incompleto" in l for l in linhas), linhas


def test_tudo_pronto_nao_marca_incompleto():
    p = Progresso([PlannedAction(tool="create_channel")] * 2)
    linhas = p.linhas([_R("create_channel"), _R("create_channel")])
    assert linhas == ["Canais: 2/2"]


def test_progresso_nao_expulsa_o_embed_de_erro(harness):
    """REGRESSAO. MAX_EMBEDS_PER_TURN e 3 e o erro e o ultimo embed acrescentado.
    Um embed de progresso proprio empurrava a explicacao da falha para fora -
    o usuario ficava sabendo que falhou, mas nao por que."""
    h = harness([
        turn(("create_category", {"name": "OK"})),
        turn(("create_channel", {"name": "bom", "type": "text"}),
             ("create_channel", {"name": "ruim", "type": "text", "category_id": "999999999"})),
        final("Parcial."),
    ], seed=False)
    out = h.ask("cria categoria e dois canais")

    kinds = [e.kind for e in out.embeds]
    assert EmbedKind.ERROR in kinds, kinds
    erro = next(e for e in out.embeds if e.kind == EmbedKind.ERROR)
    assert "ruim" in (erro.description or ""), "tem que dizer QUAL falhou"

    aviso = next(e for e in out.embeds if e.kind == EmbedKind.WARNING)
    assert "nao foi tudo" in aviso.description
    assert "Canais: 1/2" in aviso.description, "o progresso vai dentro do resumo"


def test_sem_falha_o_progresso_aparece(harness):
    """Tudo ok e mais de um tipo: o detalhamento vem, e vem como INFO."""
    h = harness([
        turn(("create_category", {"name": "A"}), ("create_channel", {"name": "b", "type": "text"})),
        final("ok"),
    ], seed=False)
    out = h.ask("cria")
    infos = [e for e in out.embeds if e.kind == EmbedKind.INFO]
    assert any("Categorias: 1/1" in (e.description or "") for e in infos), [
        (e.kind.value, e.description) for e in out.embeds
    ]


def test_resposta_do_modelo_nunca_e_cortada(harness):
    """REGRESSAO. O corte era por posicao (embeds[:3]) e a resposta do modelo
    vinha por ultimo: com 3 embeds de resultado ela sumia, e o usuario ficava sem
    resposta justamente quando havia erro para explicar."""
    from atlas.agent import MAX_EMBEDS_PER_TURN, _cortar_por_prioridade
    from atlas.embeds import EmbedSpec

    resposta = EmbedSpec(kind=EmbedKind.INFO, title="Atlas", description="Pronto.",
                         protegido=True)
    lote = [
        EmbedSpec(kind=EmbedKind.SUCCESS, title="", description="checklist"),
        EmbedSpec(kind=EmbedKind.WARNING, title="", description="resumo"),
        EmbedSpec(kind=EmbedKind.ERROR, title="", description="falhou X"),
        resposta,
    ]
    cortado = _cortar_por_prioridade(lote, MAX_EMBEDS_PER_TURN)

    assert resposta in cortado, "a resposta do modelo nao pode sumir"
    kinds = {e.kind for e in cortado}
    assert EmbedKind.ERROR in kinds, "o erro tambem nao pode sumir"
    assert EmbedKind.SUCCESS not in kinds, "o checklist e o primeiro a ceder"
    assert len(cortado) == MAX_EMBEDS_PER_TURN


def test_corte_preserva_a_ordem_de_exibicao():
    """Prioridade decide QUEM fica; a ordem de leitura continua a mesma."""
    from atlas.agent import _cortar_por_prioridade
    from atlas.embeds import EmbedSpec

    a = EmbedSpec(kind=EmbedKind.ERROR, title="", description="erro")
    b = EmbedSpec(kind=EmbedKind.INFO, title="", description="info")
    c = EmbedSpec(kind=EmbedKind.WARNING, title="", description="aviso")
    assert [e.description for e in _cortar_por_prioridade([b, a, c], 2)] == ["erro", "aviso"]


def test_pedido_pequeno_nao_ganha_progresso(harness):
    """Um tipo so nao vale uma linha a mais: o usuario pediu o minimo de texto."""
    h = harness([turn(("create_channel", {"name": "so-um", "type": "text"})), final("ok")],
                seed=False)
    out = h.ask("cria um canal")
    assert all("Categorias:" not in (e.description or "") for e in out.embeds)


# ---------------------------------------------------------------- cancelamento
def test_cancelador_e_isolado_por_guild():
    """Spec 8: cancelar o servidor A nao pode cancelar o B."""
    c = Cancelador()
    c.pedir(1)
    assert c.cancelado(1)
    assert not c.cancelado(2)


def test_limpar_zera_o_pedido():
    """Pedido antigo nao pode matar pedido novo."""
    c = Cancelador()
    c.pedir(1)
    c.limpar(1)
    assert not c.cancelado(1)


def _fila(cancelador, n):
    from atlas.audit import AuditLog
    from atlas.config import Limits
    from atlas.ratelimit import GuildRateLimiter

    feitas = []

    def dispatch(acao):
        feitas.append(acao.params.get("name"))
        return {"id": len(feitas)}

    f = ActionQueue(
        guild_id=7,
        limiter=GuildRateLimiter(1000, 1000.0),
        audit=AuditLog(),
        dispatch=dispatch,
        limits=Limits(),
        cancelador=cancelador,
    )
    f.submit_many([PlannedAction(tool="create_channel", params={"name": f"c{i}"})
                   for i in range(n)])
    return f, feitas


def test_cancelamento_para_em_ponto_seguro():
    """Spec 158: parar ENTRE acoes, e registrar o que foi e o que nao foi."""
    c = Cancelador()
    f, feitas = _fila(c, 5)
    c.pedir(7)

    resultados = f.run_all()
    assert resultados == [], "cancelado antes da primeira: nada executa"
    assert feitas == []
    eventos = [r for r in f.audit.records if r["action"] == "task.cancelled"]
    assert eventos and eventos[0]["result"] == "cancelled"
    assert eventos[0]["params"] == {"executadas": 0, "descartadas": 5}


def test_cancelamento_no_meio_preserva_o_que_ja_foi_feito():
    c = Cancelador()
    f, feitas = _fila(c, 5)

    despacho_original = f.dispatch

    def dispatch_e_cancela(acao):
        r = despacho_original(acao)
        if len(feitas) == 2:
            c.pedir(7)  # usuario cancela depois da segunda
        return r

    f.dispatch = dispatch_e_cancela
    resultados = f.run_all()

    assert feitas == ["c0", "c1"], feitas
    assert len(resultados) == 2
    assert f.pending == [], "o que nao rodou tem que sair da fila, nao ficar pendurado"
    ev = [r for r in f.audit.records if r["action"] == "task.cancelled"][0]
    assert ev["params"] == {"executadas": 2, "descartadas": 3}


def test_sem_cancelador_comporta_como_antes():
    """Spec 3: nao regredir o caminho normal."""
    f, feitas = _fila(None, 4)
    resultados = f.run_all()
    assert len(resultados) == 4 and len(feitas) == 4
