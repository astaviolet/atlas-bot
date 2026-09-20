"""Pedido acionável: cumprimento não é pedido.

Origem, medida em produção no servidor real às 21:59: o usuário mandou "ei" e o
bot respondeu "Vou criar um canal de texto chamado torneios na categoria
FORTNITE". A resposta dele foi "mas eu nem pedi". O modelo era
llm7/codestral-latest, gratuito e fraco: com um prompt de sistema que só fala de
configurar servidor, qualquer palavra vira pretexto para inventar tarefa.
"""

from __future__ import annotations

import pytest

from atlas.intencao import pedido_acionavel, resposta_para_cumprimento


# ------------------------------------------------------- o que NAO é pedido
@pytest.mark.parametrize("texto", [
    "ei",                      # <- o caso real que motivou o módulo
    "Ei!",
    "ei...",
    "oi",
    "oii",
    "olá",
    "ola",
    "opa",
    "salve",
    "bom dia",
    "boa noite",
    "tudo bem?",
    "td bem",
    "kkkk",
    "kkkkk",
    "teste",
    "testando",
    "vc ta aí?",
    "você está aí",
    "online?",
    "funciona?",
    "   ",
    "",
    "!!!",
])
def test_cumprimento_nao_e_pedido(texto):
    assert pedido_acionavel(texto) is False


@pytest.mark.parametrize("texto", [
    "<@1550239353802858626> ei",
    "<@!1550239353802858626> oi",
    "@everyone oi",
])
def test_mencao_nao_transforma_cumprimento_em_pedido(texto):
    """A menção é como o bot é chamado, não o que foi pedido."""
    assert pedido_acionavel(texto) is False


# ----------------------------------------------------------- o que É pedido
@pytest.mark.parametrize("texto", [
    "cria um canal de avisos",
    "organiza esse servidor",
    "mas eu nem pedi, remova todos os canais e deixe apenas esse",
    "apaga o canal torneios",
    "deixa o canal de avisos bonito",
    "quantos canais tem aqui?",
    "meio dia",                       # não é "boa tarde"; tem que passar
    "ei ei",                          # repetido não casa o padrão de saudação
])
def test_pedido_de_verdade_passa(texto):
    assert pedido_acionavel(texto) is True


@pytest.mark.parametrize("texto", [
    "oi, cria um canal",
    "opa! apaga o canal de testes",
    "bom dia, organiza as categorias",
])
def test_cumprimento_com_pedido_junto_e_pedido(texto):
    """O regex casa a mensagem INTEIRA de propósito. "oi, cria um canal" tem
    pedido e não pode ser engolido como saudação — senão o bot ignora o
    usuário, que é pior do que gastar uma chamada de IA."""
    assert pedido_acionavel(texto) is True


def test_resposta_para_cumprimento_e_curta_e_sem_ruido():
    """Regras permanentes: resposta curta, sem título/rodapé, sem ruído interno
    (nome de tool, checklist, contador)."""
    r = resposta_para_cumprimento("ei")
    assert len(r) < 120, f"longa demais: {r}"
    for ruido in ("tool", "classe", "token", "IA", "plano", "✅", "ℹ️"):
        assert ruido not in r, f"vazou ruído {ruido!r}: {r}"


def test_resposta_pede_o_que_a_pessoa_quer():
    """A regra permanente é SEMPRE responder. Não havendo o que executar, a
    resposta tem que abrir a conversa, não encerrar."""
    assert "?" in resposta_para_cumprimento("oi") or "diz" in resposta_para_cumprimento("oi").lower()


# --------------------------------------------------- ligacao no agente
def test_agente_nao_chama_ia_para_cumprimento(harness):
    """O ponto inteiro da correção: "ei" não pode chegar no modelo, porque é aí
    que ele inventa a tarefa."""
    h = harness([])  # roteiro VAZIO: se chamar a IA, estoura por falta de turno
    outcome = h.ask("ei")

    assert outcome.embeds, "a regra é sempre responder"
    assert outcome.results == [], "cumprimento não pode gerar ação"
    assert outcome.embeds[0].description, "resposta vazia"


def test_agente_responde_cumprimento_sem_executar_nada(harness):
    h = harness([])
    antes = dict(h.gateway.channels)
    h.ask("<@1550239353802858626> oi")
    assert h.gateway.channels == antes, "cumprimento mudou o servidor"
