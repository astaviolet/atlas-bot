"""Botões de confirmação (spec 73).

A spec lista sete validações para todo botão sensível: usuário, guild, sessão,
ação, expiração, permissões, e executar apenas o plano correspondente.

POR QUE A VALIDAÇÃO É FUNÇÃO PURA E NÃO ESTÁ NO CALLBACK
--------------------------------------------------------
O callback do discord.py é difícil de testar: precisa de interação real,
gateway conectado e permissão de verdade. Se a validação morar lá, ela nunca é
testada — e botão de confirmação não testado é como confirmação que não existe.

Então `validar_clique` recebe só dados (ids, custom_id, sessão, relógio) e
devolve o veredito. O callback do Discord só traduz interação em chamada e a
resposta em mensagem. A parte que importa fica coberta por teste.

AS SETE BARREIRAS, NA ORDEM EM QUE RODAM
----------------------------------------
A ordem não é decorativa: cada uma rejeita antes da próxima gastar trabalho, e
a mais barata vem primeiro.

1. guild        — o clique veio do servidor da sessão? (spec 8)
2. sessão       — existe confirmação pendente neste canal?
3. expiração    — ela ainda vale? (spec 19: botão antigo não executa plano novo)
4. ação         — o custom_id é um dos esperados?
5. token        — o custom_id carrega o token DO plano pendente? Sem isto um
                  botão de uma confirmação velha executa a nova (spec 18).
6. usuário      — quem clica é quem pediu? (spec 7/73)
7. permissão    — checada na execução, não aqui: a permissão real só se conhece
                  na hora de chamar a API, e conferir duas vezes daria janela
                  para mudar entre as duas.

NENHUMA delas confia em dado que veio do clique para decidir autorização. O
`guild_id` usado é o da interação real, nunca um campo do payload.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

ACAO_CONFIRMAR = "atlas_confirmar"
ACAO_CANCELAR = "atlas_cancelar"
ACOES_VALIDAS = frozenset({ACAO_CONFIRMAR, ACAO_CANCELAR})


@dataclass
class CliqueValidado:
    ok: bool
    motivo: str = ""
    #: "confirmar" ou "cancelar". None quando o clique foi recusado.
    decidir: str | None = None
    token: str | None = None


def montar_custom_id(acao: str, token: str) -> str:
    """O token vai no custom_id de propósito: é o que amarra o clique ao plano.

    Sem ele, um botão que ficou na tela de uma confirmação anterior executaria a
    confirmação seguinte — que é exatamente o caso da spec 18/19.
    """
    return f"{acao}:{token}"


def ler_custom_id(custom_id: str) -> tuple[str | None, str | None]:
    """Devolve (acao, token). (None, None) se o formato não é nosso."""
    bruto = (custom_id or "").strip()
    if ":" not in bruto:
        return None, None
    acao, _, token = bruto.partition(":")
    if acao not in ACOES_VALIDAS or not token.strip():
        return None, None
    return acao, token.strip()


def validar_clique(
    *,
    custom_id: str,
    guild_id_clique: int | None,
    user_id_clique: int | None,
    session: Any,
) -> CliqueValidado:
    """As sete barreiras da spec 73. Nunca levanta."""
    try:
        # 1. guild — isolamento absoluto (spec 8)
        if guild_id_clique is None or int(guild_id_clique) != int(session.guild_id):
            return CliqueValidado(False, "guild_diferente")

        # 2. sessão — tem confirmação pendente neste canal?
        pendente = getattr(session, "pending", None)
        if pendente is None:
            return CliqueValidado(False, "sem_confirmacao_pendente")

        # 3. expiração (spec 19). O prazo vem do relogio da sessao, nao de um
        # argumento: duas fontes de tempo diferentes e uma delas sempre mente.
        if session.confirmacao_vencida():
            return CliqueValidado(False, "confirmacao_expirada")

        # 4. ação conhecida
        acao, token = ler_custom_id(custom_id)
        if acao is None:
            return CliqueValidado(False, "acao_desconhecida")

        # 5. token — o clique tem que ser DESTE plano (spec 18)
        if token != str(pendente.token):
            return CliqueValidado(False, "token_nao_confere")

        # 6. usuário — quem clica é quem pediu
        autor = getattr(session, "source_author_id", None)
        if user_id_clique is None or (autor is not None
                                      and int(user_id_clique) != int(autor)):
            return CliqueValidado(False, "usuario_nao_e_o_autor")

        # 7. permissão é checada na execução (ver docstring)
        return CliqueValidado(
            True,
            decidir="confirmar" if acao == ACAO_CONFIRMAR else "cancelar",
            token=token,
        )
    except Exception:  # noqa: BLE001 - validação de segurança nunca levanta
        log.exception("falha inesperada ao validar clique de botao")
        return CliqueValidado(False, "erro_interno")


def mensagem_de_recusa(motivo: str) -> str:
    """Texto curto para o usuário. Sem detalhe interno (spec 112)."""
    return {
        "guild_diferente": "Esse botão é de outro servidor.",
        "sem_confirmacao_pendente": "Não tenho nenhuma confirmação pendente aqui.",
        "confirmacao_expirada": "Essa confirmação venceu. Me pede de novo.",
        "acao_desconhecida": "Não reconheci esse botão.",
        "token_nao_confere": "Esse botão é de um plano antigo. Me pede de novo.",
        "usuario_nao_e_o_autor": "Só quem pediu pode confirmar isso.",
        "erro_interno": "Algo deu errado ao ler o clique. Me chama por texto.",
    }.get(motivo, "Não consegui processar esse clique.")
