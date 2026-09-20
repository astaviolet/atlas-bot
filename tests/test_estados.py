"""Estados do agente (spec 113) e prioridade (spec 115)."""

from __future__ import annotations

from conftest import final, turn

from atlas.estados import (
    AgentState,
    Prioridade,
    RastreadorDeEstado,
    aceita_saude,
    mais_urgente,
    tolerancia,
)


class _Relogio:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 1.0
        return self.t


# ------------------------------------------------------------------ estados 113
def test_caminho_completo_de_um_pedido():
    r = RastreadorDeEstado(clock=_Relogio())
    assert r.estado == AgentState.IDLE
    for e in (AgentState.UNDERSTANDING, AgentState.PLANNING,
              AgentState.EXECUTING, AgentState.VERIFYING, AgentState.COMPLETED):
        assert r.ir_para(e), e
    assert [x for x, _ in r.historico] == [
        "idle", "understanding", "planning", "executing", "verifying", "completed",
    ]


def test_pular_etapa_e_registrado_como_invalido():
    """PLANNING -> COMPLETED sem executar e o 'disse que fez sem fazer' (185).
    Mas nao pode derrubar o pedido: e diagnostico, nao excecao."""
    r = RastreadorDeEstado()
    r.ir_para(AgentState.UNDERSTANDING)
    r.ir_para(AgentState.PLANNING)
    r.ir_para(AgentState.VERIFYING)  # nao da para verificar o que nao executou
    assert r.estado == AgentState.PLANNING, "a transicao invalida nao se aplica"
    assert r.transicoes_invalidas == ["planning -> verifying"]


def test_ficar_no_mesmo_estado_nao_e_transicao():
    r = RastreadorDeEstado()
    r.ir_para(AgentState.UNDERSTANDING)
    assert r.ir_para(AgentState.UNDERSTANDING)
    assert len(r.historico) == 2, "repetir nao pode inflar o historico"


def test_reiniciar_limpa_tudo():
    r = RastreadorDeEstado()
    r.ir_para(AgentState.UNDERSTANDING)
    r.ir_para(AgentState.FAILED)
    r.reiniciar()
    assert r.estado == AgentState.IDLE
    assert r.transicoes_invalidas == []
    assert len(r.historico) == 1


def test_pedido_real_devolve_estado_e_caminho(harness):
    h = harness([turn(("create_channel", {"name": "x", "type": "text"})), final("ok")],
                seed=False)
    out = h.ask("cria um canal")
    assert out.estado == "completed", out.estado
    assert out.caminho[0] == "idle" and out.caminho[1] == "understanding"
    assert "executing" in out.caminho, out.caminho


def test_tudo_falhou_vira_failed(harness):
    h = harness([turn(("create_channel", {"name": "x", "type": "text",
                                        "category_id": "999999999"})), final("ok")],
                seed=False)
    out = h.ask("cria")
    assert out.estado == "failed", (out.estado, out.caminho)


# ---------------------------------------------------------------- prioridade 115
def test_ordem_de_urgencia():
    assert mais_urgente(Prioridade.DISCOVERY, Prioridade.SECURITY) == Prioridade.SECURITY
    assert mais_urgente(Prioridade.USER_ACTION, Prioridade.BACKGROUND) == Prioridade.USER_ACTION
    # tolerancia = nivel maximo de degradacao aceito. Maior = mais tolerante.
    assert tolerancia(Prioridade.SECURITY) <= tolerancia(Prioridade.USER_ACTION)
    assert tolerancia(Prioridade.USER_ACTION) > tolerancia(Prioridade.DISCOVERY), \
        "pedido do usuario pode usar rota pior que a sondagem de discovery"
    assert tolerancia(Prioridade.DISCOVERY) == 0


def test_usuario_aceita_rota_degradada_discovery_nao():
    """Spec 59: responder devagar vale mais que nao responder. Mas sondar
    provider com rota ruim queima cota gratuita e piora a saude medida."""
    assert aceita_saude(Prioridade.USER_ACTION, 1), "degradada serve para o usuario"
    assert not aceita_saude(Prioridade.DISCOVERY, 1), "discovery so usa saudavel"
    assert aceita_saude(Prioridade.DISCOVERY, 0)
