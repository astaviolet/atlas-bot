"""Classificação da tarefa para escolha de modelo (spec 107).

A spec pede: classificar em SIMPLES, MÉDIA, COMPLEXA, ESTRUTURAL, TOOL-HEAVY e
LONG-CONTEXT, e escolher modelo adequado — não usar modelo caro/pesado para
tarefa simples sem necessidade.

O QUE ISTO MUDA DE VERDADE NO CÓDIGO
-------------------------------------
Duas coisas, e só duas:

1. **Requisito de capacidade.** Tarefa que vai chamar tool exige `tool_calling`
   de verdade. Antes o router deduzia isso de `bool(tools)` — o que funciona,
   mas confunde "o agente tem tools disponíveis" com "esta tarefa vai usá-las".
   Um "quais canais existem?" não precisa de tool calling do modelo se a
   leitura já veio no contexto.

2. **Critério de desempate.** SIMPLES prefere a rota mais rápida; ESTRUTURAL e
   COMPLEXA preferem a mais confiável. O router já ordena por
   (falhas, carga, latência) — então a diferença real é qual chave pesa, e isso
   é o que `prefere_rapida` devolve.

O QUE ISTO **NÃO** FAZ, E POR QUÊ
----------------------------------
Não escolhe "modelo caro vs barato": o pool é inteiro gratuito e anônimo, não há
preço para ponderar. Inventar um eixo de custo que não existe seria exatamente a
configuração inventada que a spec 185 proíbe. Quando houver provider pago no
pool, o eixo entra aqui.
"""

from __future__ import annotations

import re
from enum import Enum

from .providers import Capabilities


class ClasseTarefa(str, Enum):
    SIMPLES = "simples"
    MEDIA = "media"
    COMPLEXA = "complexa"
    ESTRUTURAL = "estrutural"
    TOOL_HEAVY = "tool_heavy"
    LONG_CONTEXT = "long_context"


#: Palavras que indicam projeto de estrutura, não operação pontual.
_PADRAO_ESTRUTURAL = re.compile(
    r"\b(servidor|comunidade|cl[ãa]|estrutura|arquitetura|organiza|reorganiza|"
    r"refaz|reconstr[óo]i|arruma|deixa\s+(esse|isso)\s+bonit|profissional|"
    r"tem[áa]tic|onboarding|hierarquia)\b",
    re.I,
)

#: Palavras que indicam uma operação única e pequena.
_PADRAO_SIMPLES = re.compile(
    r"^\s*(cria|crie|apaga|exclui|renomeia|move|adiciona|tira|muda)\b",
    re.I,
)

#: A partir de quantos caracteres de histórico a tarefa vira LONG_CONTEXT.
_LIMIAR_CONTEXTO = 12_000


def classificar(
    texto: str,
    *,
    vai_usar_tools: bool = True,
    n_acoes: int = 0,
    tam_contexto: int = 0,
) -> ClasseTarefa:
    """Classifica o pedido. Nunca levanta: na dúvida, MÉDIA.

    Classificar errado para cima custa latência; para baixo custa capacidade.
    Por isso o empate vai para MÉDIA, que exige tool calling mas não privilegia
    velocidade.
    """
    texto = texto or ""

    if tam_contexto >= _LIMIAR_CONTEXTO:
        return ClasseTarefa.LONG_CONTEXT

    if n_acoes >= 10:
        return ClasseTarefa.TOOL_HEAVY

    estrutural = bool(_PADRAO_ESTRUTURAL.search(texto))
    simples = bool(_PADRAO_SIMPLES.match(texto.strip())) and len(texto) < 60

    if estrutural:
        return ClasseTarefa.ESTRUTURAL
    if simples and n_acoes <= 1 and not vai_usar_tools:
        return ClasseTarefa.SIMPLES
    if simples:
        return ClasseTarefa.MEDIA
    if len(texto) > 400:
        return ClasseTarefa.COMPLEXA
    return ClasseTarefa.MEDIA


def exigencias(classe: ClasseTarefa, *, tools_disponiveis: bool = True) -> Capabilities:
    """O que a rota PRECISA saber fazer para esta classe."""
    if classe == ClasseTarefa.LONG_CONTEXT:
        # structured_output nao e exigido aqui de proposito: exigir capacidade que
        # quase nenhuma rota gratuita tem deixaria o pool inteiro de fora, e a
        # spec 59 manda nao dizer "nao consigo" enquanto houver alternativa.
        return Capabilities(tool_calling=tools_disponiveis)
    return Capabilities(tool_calling=tools_disponiveis)


def prefere_rapida(classe: ClasseTarefa) -> bool:
    """SIMPLES quer a mais rápida; o resto quer a mais confiável."""
    return classe == ClasseTarefa.SIMPLES


def rotulo(classe: ClasseTarefa) -> str:
    """Para o painel e para o log: o nome legível, não o enum."""
    return {
        ClasseTarefa.SIMPLES: "simples",
        ClasseTarefa.MEDIA: "média",
        ClasseTarefa.COMPLEXA: "complexa",
        ClasseTarefa.ESTRUTURAL: "estrutural",
        ClasseTarefa.TOOL_HEAVY: "tool-heavy",
        ClasseTarefa.LONG_CONTEXT: "contexto longo",
    }[classe]
