"""Classe da tarefa -> escolha de modelo (spec 107)."""

from __future__ import annotations

from conftest import final, turn

from atlas.ai.classificacao import (
    ClasseTarefa,
    classificar,
    exigencias,
    prefere_rapida,
    rotulo,
)


def test_pedido_de_servidor_e_estrutural():
    assert classificar("faz um servidor de Fortnite competitivo") == ClasseTarefa.ESTRUTURAL
    assert classificar("organiza essa bagunca") == ClasseTarefa.ESTRUTURAL
    assert classificar("deixa esse servidor bonito") == ClasseTarefa.ESTRUTURAL


def test_pedido_curto_e_simples_so_sem_tool():
    """SIMPLES exige nao usar tool: se vai agir no Discord, nao e trivial."""
    assert classificar("cria um canal chamado regras", vai_usar_tools=False) == ClasseTarefa.SIMPLES
    assert classificar("cria um canal chamado regras", vai_usar_tools=True) == ClasseTarefa.MEDIA


def test_muitas_acoes_vira_tool_heavy():
    assert classificar("cria canais", n_acoes=12) == ClasseTarefa.TOOL_HEAVY


def test_contexto_grande_vira_long_context():
    assert classificar("oi", tam_contexto=20_000) == ClasseTarefa.LONG_CONTEXT
    assert classificar("oi", tam_contexto=1_000) != ClasseTarefa.LONG_CONTEXT


def test_texto_longo_e_complexo():
    assert classificar("quero " + "detalhe " * 80) == ClasseTarefa.COMPLEXA


def test_na_duvida_vai_para_media():
    """Errar para cima custa latencia; para baixo custa capacidade. Media e o
    meio termo que exige tool calling sem privilegiar velocidade."""
    assert classificar("") == ClasseTarefa.MEDIA
    assert classificar("hmm") == ClasseTarefa.MEDIA


def test_toda_classe_tem_rotulo_e_exigencia():
    """Nenhuma classe pode ficar sem mapping: KeyError em runtime seria pior."""
    for c in ClasseTarefa:
        assert rotulo(c)
        caps = exigencias(c, tools_disponiveis=True)
        assert caps.tool_calling is True


def test_sem_tools_nao_exige_tool_calling():
    assert exigencias(ClasseTarefa.MEDIA, tools_disponiveis=False).tool_calling is False


def test_so_simples_prefere_rapida():
    assert prefere_rapida(ClasseTarefa.SIMPLES)
    for c in ClasseTarefa:
        if c != ClasseTarefa.SIMPLES:
            assert not prefere_rapida(c), c


def test_router_desempata_por_latencia_quando_e_simples():
    """Duas rotas igualmente saudaveis: a mais rapida tem que vencer para
    pedido simples. Sem isso a 'preferencia' da spec 107 seria decoracao."""
    from atlas.ai.providers import Capabilities, Gateway, ModelRoute
    from atlas.ai.router import Router

    def montar():
        rapida = ModelRoute(gateway="g", model="rapida", caps=Capabilities(tool_calling=True))
        lenta = ModelRoute(gateway="g", model="lenta", caps=Capabilities(tool_calling=True))
        g = Gateway(id="g", base_url="http://x", models=[rapida, lenta])
        r = Router(catalog=[g], client_factory=lambda gw: None)
        # mesma saude, mesma carga: so a latencia diferencia
        r.health.record_success("g/rapida", latency_ms=100.0)
        r.health.record_success("g/lenta", latency_ms=900.0)
        return r

    precisa = Capabilities(tool_calling=True)
    assert montar().escolher(precisa, prefere_rapida=True).model == "rapida"
    assert montar().escolher(precisa, prefere_rapida=False) is not None


def test_confiabilidade_vem_antes_de_velocidade():
    """Rapidez nao justifica insistir em rota que esta falhando: a rota rapida
    porem quebrada nao pode vencer so por ser rapida."""
    from atlas.ai.providers import Capabilities, Gateway, ModelRoute
    from atlas.ai.router import Router

    rapida = ModelRoute(gateway="g", model="rapida", caps=Capabilities(tool_calling=True))
    lenta = ModelRoute(gateway="g", model="lenta", caps=Capabilities(tool_calling=True))
    g = Gateway(id="g", base_url="http://x", models=[rapida, lenta])
    r = Router(catalog=[g], client_factory=lambda gw: None)
    r.health.record_success("g/rapida", latency_ms=10.0)
    r.health.record_success("g/lenta", latency_ms=900.0)
    for _ in range(3):
        r.health.record_failure("g/rapida", reason="timeout", retryable=True)

    escolhida = r.escolher(Capabilities(tool_calling=True), prefere_rapida=True)
    assert escolhida is not None and escolhida.model == "lenta", escolhida


def test_agente_classifica_e_registra(harness):
    """A classificacao tem que chegar na auditoria, senao e decoracao."""
    h = harness([turn(("create_channel", {"name": "x", "type": "text"})), final("ok")],
                seed=False)
    h.ask("cria um canal chamado x")
    eventos = [r for r in h.audit.records if r["action"] == "ai.task_class"]
    assert eventos, "a classe tem que ficar registrada"
    assert eventos[0]["params"]["classe"] in {c.value for c in ClasseTarefa}
