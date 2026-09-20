"""Classe da tarefa -> escolha de modelo (spec 107)."""

from __future__ import annotations


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
