"""Doutrina de design de servidores Discord.

POR QUE ISTO EXISTE COMO MODULO SEPARADO
----------------------------------------
O pedido do usuario era um documento de 46 secoes (~10 mil tokens). Colar tudo
em toda chamada de IA contradiria duas regras permanentes do proprio projeto:
resposta o mais curta/direta possivel com o minimo de token, e velocidade. Cada
token de prompt e reenviado em CADA volta do agente - 10 mil tokens x 4 voltas
seria o pedido inteiro dominado por texto que 95% das vezes nao se aplica.

Entao: a doutrina entra no prompt SO quando o pedido e de projetar/criar um
servidor ou uma estrutura grande. A decisao e deterministic, em codigo
(`is_pedido_de_design`), nao deixada ao criterio do modelo.

SOBRE "PESQUISA CONTINUA NA INTERNET" (secoes 1, 24, 38, 39, 45 do pedido)
--------------------------------------------------------------------------
NAO esta implementada, e a ausencia e deliberada:
  - O bot tem 21 tools fixas, todas de operacao no Discord. Nao ha tool de
    busca na web, e adicionar uma quebraria a lista fechada que o proprio
    usuario definiu.
  - Pesquisar na web a cada pedido acrescentaria segundos - exatamente o que o
    usuario acabou de reclamar.
  - O proprio documento diz que o objetivo e guardar PRINCIPIOS, nao copiar
    servidores, e proibe scraping agressivo. Os principios estao abaixo.
Se um dia quiser busca ao vivo, e uma tool nova + decisao explicita, nao algo
para enfiar de contrabando aqui.
"""

from __future__ import annotations

import logging
import re
from typing import Any

#: Palavras que indicam "projetar uma estrutura", nao "fazer uma operacao".
#: Mantido curto de proposito: falso positivo custa ~800 tokens em todo pedido.
_GATILHOS = (
    r"\bcri(?:e|a|ar)\b[^.]{0,40}\bservidor\b",
    r"\bservidor\b[^.]{0,40}\b(?:bonit|tematic|completo|profissional|organizad)",
    r"\b(?:monta|montar|constru|estrutura|arquitetura|layout)\b[^.]{0,40}"
    r"\b(?:servidor|comunidade|canais)\b",
    r"\bfaz(?:er)?\s+bonit",
    r"\bdeixa\s+bonit",
    r"\breorganiza",
    r"\btematic[oa]\b",
    r"\bonboarding\b",
    r"\bcategorias?\b[^.]{0,30}\bcanais\b",
)
logger = logging.getLogger(__name__)

_RE_GATILHO = re.compile("|".join(_GATILHOS), re.IGNORECASE)

#: Operacoes simples que por acaso contem uma palavra de gatilho.
_NEGATIVOS = re.compile(
    r"\b(?:apag|exclu|remov|renomei|troca|muda|cite|lista|mostre|qual|quant)\w*",
    re.IGNORECASE,
)


def is_pedido_de_design(texto: str) -> bool:
    """ Decide se o pedido e de projetar uma estrutura.

    Deterministico e testado: "cite todos os cargos" NAO pode cair aqui, senao
    todo pedido simples paga ~800 tokens de doutrina e fica mais lento.
    """
    if not texto or not texto.strip():
        return False
    if not _RE_GATILHO.search(texto):
        return False
    # "apague o canal de categorias" nao e projeto de servidor.
    if _NEGATIVOS.search(texto) and len(texto.split()) < 6:
        return False
    return True


DOUTRINA = """PROJETO DE SERVIDOR (vale so para este pedido)

Voce esta projetando uma comunidade, nao criando canais. Antes de chamar
qualquer tool, decida internamente: tema, objetivo, publico, tamanho esperado,
tipo de comunidade e o caminho que uma pessoa nova percorre.

ORDEM: tema -> objetivo -> publico -> jornada -> categorias -> canais -> cargos
-> permissoes -> identidade visual -> executar -> conferir.

JORNADA DE QUEM ENTRA: chegada -> boas-vindas -> regras -> escolha de cargos ->
area principal -> recursos do tema. Adapte, nao decore.

CATEGORIAS sao areas conceituais, nao sacos de canais. Se voce nao consegue
dizer em uma frase o que cada categoria resolve, ela nao deveria existir.

MENOS, POREM MELHOR. Para cada canal pergunte: que problema resolve, quem usa,
com que frequencia, poderia ser juntado com outro, e texto/voz/forum? Sem
funcao clara, NAO CRIE. Servidor pequeno nao leva arquitetura gigante.

NAO USE TEMPLATE UNIVERSAL. Proibido responder todo tema com
INFORMACAO/COMUNIDADE/GAMING/VOZ/STAFF. A estrutura nasce do tema: competitivo
pede lfg, scrims, torneios, resultados, recrutamento; RP pede faccoes, regras
de RP, suporte; loja pede produtos, pedidos, atendimento; criador pede conteudo,
divulgacao, feedback.

IDENTIDADE VISUAL: escolha UMA linguagem e mantenha. Ou "📢・anuncios" em tudo,
ou "「💬」chat" em tudo. Nunca misture 「x」, ┃, ・ e 💎 no mesmo servidor.
Emoji com moderação: um por nome no maximo, e nunca emoji repetido como enfeite.
Nomes curtos, minusculos, sem acento, legiveis.

CARGOS em camadas: dono > admin > gerente > moderador > ajudante > cargos de
funcao > comunidade. Separe cargo FUNCIONAL (tem permissao real) de cargo de
IDENTIDADE (cor, regiao, plataforma, jogo, nivel) - cargo estetico NUNCA ganha
permissao administrativa. So crie os que fazem sentido para este tema.

PERMISSOES: menor privilegio. @everyone ve o minimo necessario; areas de staff,
logs e moderacao ficam privadas e invisiveis para quem nao e da equipe.

NAO ESQUECA voz (lobby, squads/duos, uma sala de competitivo) e considere forum
quando o assunto for discussao recorrente. Nao crie 20 canais de voz vazios.

SE O SERVIDOR JA EXISTE: preserve o que funciona. Reconstruir nao e apagar tudo.
Mudanca grande ou destrutiva exige plano + resumo + confirmacao explicita antes.

ANTES DE TERMINAR, confira: nomes coerentes, um so estilo visual, sem canal
duplicado ou inutil, cargos com hierarquia que faz sentido, sem permissao
perigosa, e uma pessoa nova entendendo para onde ir. Se algo estiver ruim,
corrija antes de responder - nao compense design fraco com mais canais."""


def doutrina_de_design(texto: str) -> str:
    """Devolve a doutrina se o pedido for de projeto; senao, string vazia."""
    return DOUTRINA if is_pedido_de_design(texto) else ""


# ---------------------------------------------------------------------------
# Fase 22: proposta concreta (spec 11, 26, 130, 135)
# ---------------------------------------------------------------------------
def proposta_de_design(texto: str, n_membros: int | None = None) -> str:
    """Projeta a arquitetura e devolve como proposta concreta.

    POR QUE ISTO E DIFERENTE DA DOUTRINA
    ------------------------------------
    A doutrina (acima) diz "como pensar". Medido na Fase 5: o modelo ignorou.
    Isto aqui diz "o que construir", com nome de categoria, canal e cargo. E
    gerado por composicao deterministica em `design_system`, entao e testavel -
    e muito mais dificil de ignorar do que um paragrafo de principio.

    Continua sendo PROPOSTA, nao execucao (spec 11: plano != execucao). O modelo
    ainda emite as tool calls, e tudo passa pelas mesmas barreiras.
    """
    from .design_system import (
        Briefing,
        design_score,
        inferir_dominio,
        inferir_estilo,
        inferir_porte,
        projetar,
    )

    if not is_pedido_de_design(texto):
        return ""

    briefing = Briefing(
        tema=texto,
        dominio=inferir_dominio(texto),
        porte=inferir_porte(n_membros),
        estilo=inferir_estilo(texto),
    )
    arq = projetar(briefing)
    nota = design_score(arq)

    linhas = [
        "PROPOSTA DE ARQUITETURA (gerada pelo sistema de design; use como base,",
        "adaptando o vocabulario ao tema - nao copie para outro tipo de servidor):",
        "",
    ]
    for cat in arq.categorias:
        linhas.append(f"[{cat.nome}] {cat.proposito}")
        for c in cat.canais:
            vis = " (privado)" if c.privado else ""
            linhas.append(f"  - {c.nome} [{c.tipo}]{vis}: {c.proposito}")
    funcionais = [c.nome for c in arq.cargos if c.tipo == "funcional"]
    identidade = [c.nome for c in arq.cargos if c.tipo == "identidade"]
    linhas.append("")
    linhas.append(f"Cargos funcionais (hierarquia): {', '.join(funcionais)}")
    linhas.append(f"Cargos de identidade (cor/interesse, sem permissao): {', '.join(identidade)}")
    linhas.append(f"Jornada de entrada: {' -> '.join(arq.onboarding)}")
    linhas.append(
        f"Porte considerado: {briefing.porte.value} | estilo: {briefing.estilo.value} "
        f"| dominio: {briefing.dominio.value} | nota interna: {nota['geral']}/10"
    )
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Fase 26: proposta de reforma (spec 45, 46, 84, 131)
# ---------------------------------------------------------------------------
_RE_REFORMA = re.compile(
    r"\b(?:arrum|organiz|refaz|reconstru|reform|melhor|limp|otimiz)\w*",
    re.IGNORECASE,
)


def is_pedido_de_reforma(texto: str) -> bool:
    """Pedidos curtos da spec 131: "arruma esse servidor", "organiza",
    "faz bonito". Determinístico, como `is_pedido_de_design`.

    Não basta conter a palavra: "arruma o nome do canal" é operação simples, e
    jogar um plano de reforma inteiro ali custaria tokens e confundiria.
    """
    if not texto or not texto.strip():
        return False
    if not _RE_REFORMA.search(texto):
        return False
    palavras = texto.split()
    # pedido curto sem alvo explicito ("organiza") e reforma do servidor inteiro
    if len(palavras) <= 2:
        return True
    # com alvo pontual, nao e reforma de servidor
    if re.search(r"\b(?:canal|cargo|categoria|nome|topico|tópico)\b", texto, re.IGNORECASE):
        return False
    return True


def proposta_de_reforma(texto: str, snapshot: Any, n_membros: int | None = None) -> str:
    """Audita o servidor REAL e devolve o plano de reforma como texto.

    Diferença para `proposta_de_design`: aquilo projeta do zero, isto parte do
    que já existe. Por isso precisa do snapshot — sem ele não há o que
    reaproveitar e a "reforma" viraria reconstrução, que é o que a spec 46
    proíbe como padrão.
    """
    from .design_system import (
        Briefing,
        inferir_dominio,
        inferir_estilo,
        inferir_porte,
    )
    from .reforma import nomenclatura_dominante, planejar_reforma

    if not is_pedido_de_reforma(texto):
        return ""
    if snapshot is None:
        return ""

    briefing = Briefing(
        tema=texto,
        dominio=inferir_dominio(texto),
        porte=inferir_porte(n_membros),
        # segue o estilo que o servidor ja usa em vez de impor outro (spec 46)
        estilo=inferir_estilo(texto),
    )
    try:
        reforma = planejar_reforma(snapshot, briefing)
        estilo_atual = nomenclatura_dominante(snapshot)
    except Exception:
        # Reforma que falha nao pode derrubar o pedido. O modelo segue sem a
        # proposta, e o erro vai para o log de verdade - nao some em silencio.
        logger.exception("proposta de reforma falhou")
        return ""

    linhas = [
        "AUDITORIA DO SERVIDOR ATUAL",
    ]
    if reforma.achados:
        for a in reforma.achados:
            linhas.append(f"  [{a.severidade}] {a.problema}")
    else:
        linhas.append("  nenhum defeito objetivo encontrado")
    linhas.append("")
    linhas.append("PLANO DE REFORMA (reaproveita o que existe; NADA é excluído):")
    for a in reforma.renomear:
        linhas.append(f"  renomear {a.params} — {a.motivo}")
    for a in reforma.mover:
        linhas.append(f"  mover {a.params} — {a.motivo}")
    for a in reforma.criar:
        linhas.append(f"  criar {a.params} — {a.motivo}")
    linhas.append("")
    linhas.append(f"Impacto: {reforma.impacto().replace(chr(10), ' | ')}")
    linhas.append(f"Nomenclatura em uso no servidor: {estilo_atual.value} (siga esta)")
    if reforma.suspeitas:
        linhas.append(
            "Canais que parecem sobra — NÃO exclua sem o usuário confirmar: "
            + ", ".join(reforma.suspeitas[:12])
        )
    return "\n".join(linhas)
