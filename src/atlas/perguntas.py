"""Perguntas objetivas quando falta detalhe (spec 130, 132).

A REGRA QUE GOVERNA ESTE MÓDULO
-------------------------------
Spec 130: "se faltarem detalhes importantes, fazer perguntas objetivas. Não
perguntar coisas que podem ser inferidas com segurança."
Spec 132: "inferências reversíveis podem ser feitas. Mudanças destrutivas não."

Juntando as duas: **perguntar é exceção, não padrão.** Quase todo pedido deve
voltar com lista vazia. Tema, porte, público e estilo são inferíveis — e errar
neles é reversível (renomear canal custa uma tool call). O que NÃO é inferível é
o que é irreversível.

O ÚNICO CASO EM QUE ESTE MÓDULO PERGUNTA
----------------------------------------
Reforma com canais que sobraram. Excluir canal destrói o histórico dele e não há
rollback para conteúdo — o snapshot guarda estrutura, não mensagens. Decidir isso
sozinho seria exatamente o que a spec 132 proíbe. Então a pergunta é "o que faço
com estes?", nunca "qual tema você quer?".

POR QUE NÃO PERGUNTAR O TEMA
----------------------------
"Monta um servidor" sem tema cai em COMUNIDADE, que é uma estrutura genérica
funcional e reversível. Perguntar ali seria travar o pedido por algo que dá para
decidir e corrigir depois — e o usuário já disse explicitamente para não
perguntar o que dá para decidir sozinho.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Acima disto a lista de sobras vai truncada na pergunta. Vinte nomes numa
#: pergunta não é pergunta objetiva, é despejo.
_MAXITENS_NA_PERGUNTA = 8


@dataclass(frozen=True)
class Pergunta:
    texto: str
    #: Por que isto não pôde ser inferido. Sem isto a pergunta é preguiça.
    motivo: str
    #: O que acontece se o usuário não responder. Tem que haver um caminho.
    padrao_se_sem_resposta: str


def perguntas_necessarias(
    *,
    suspeitas: list[str] | None = None,
    destruicoes_pendentes: int = 0,
) -> list[Pergunta]:
    """Devolve as perguntas que realmente precisam ser feitas.

    Lista vazia é o resultado normal e esperado. Se este módulo começar a
    perguntar com frequência, ele está errado — não o usuário.
    """
    saida: list[Pergunta] = []

    sobras = [s for s in (suspeitas or []) if str(s).strip()]
    if sobras:
        amostra = sobras[:_MAXITENS_NA_PERGUNTA]
        resto = f" e mais {len(sobras) - len(amostra)}" if len(sobras) > len(amostra) else ""
        saida.append(Pergunta(
            texto=(
                f"Sobraram {len(sobras)} canais fora da estrutura nova: "
                f"{', '.join(amostra)}{resto}. Deixo como estão ou apago?"
            ),
            motivo=(
                "excluir canal destrói o histórico dele e não há rollback para "
                "conteúdo — o snapshot guarda estrutura, não mensagens"
            ),
            padrao_se_sem_resposta="deixar como estão (nada é excluído sem resposta)",
        ))

    if destruicoes_pendentes > 0:
        saida.append(Pergunta(
            texto=(
                f"São {destruicoes_pendentes} exclusões. Confirma?"
            ),
            motivo="exclusão em quantidade é irreversível (spec 132)",
            padrao_se_sem_resposta="não executar",
        ))

    return saida


def formatar_perguntas(perguntas: list[Pergunta]) -> str:
    """Uma mensagem só, curta. Duas perguntas viram duas linhas, não dois
    parágrafos — o usuário pediu o mínimo que resolve."""
    if not perguntas:
        return ""
    if len(perguntas) == 1:
        return perguntas[0].texto
    return "\n".join(f"- {p.texto}" for p in perguntas)
