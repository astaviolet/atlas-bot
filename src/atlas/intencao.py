"""Pedido acionável: separar cumprimento de pedido, em código.

POR QUE ISTO EXISTE
-------------------
Medido em produção, servidor real, 21:59: o usuário mandou "ei" e o bot respondeu
"Vou criar um canal de texto chamado torneios na categoria FORTNITE." O usuário
não tinha pedido nada — a resposta dele foi "mas eu nem pedi".

O modelo era llm7/codestral-latest, gratuito e fraco. Com um prompt de sistema
cheio de "você configura servidores", qualquer palavra vira pretexto para inventar
uma tarefa. `classificar()` não pega isso: ela mede COMPLEXIDADE (devolve MEDIA
para "ei" e para "cria um canal"), não INTENÇÃO.

Regra do projeto: prompt não segura, enforcement em código. Então a decisão de
"isto não é pedido" é determinística e acontece ANTES de gastar chamada de IA.
"""

from __future__ import annotations

import re
import unicodedata

#: Cumprimento puro. Casa a mensagem inteira, não um pedaço — "oi, cria um
#: canal" TEM pedido e não pode cair aqui.
# ATENCAO: este regex roda SOBRE O TEXTO JA SEM ACENTO (_sem_acento). Padrao com
# acento aqui nunca casa - foi o bug que "voce esta ai" pegou.
_SAUDACAO = re.compile(
    r"^(?:ei+|eai|e[ -]?ai|eae|oi+|ola|hey+|hello+|opa+|salve|bom dia|boa tarde|"
    r"boa noite|td bem|tudo bem|tudo certo|blz|beleza|show|joia|kkk+|hehe|"
    r"ta ai|testando|teste|vc ta ai|voce (?:ta|esta) ai|"
    r"esta ai|online\??|acordado\??|funciona\??|funcionando\??)[\s!.?,]*$",
    re.IGNORECASE,
)

#: Só pontuação, emoji ou ruído.
_VAZIO = re.compile(r"^[\s\W_]*$", re.UNICODE)


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def pedido_acionavel(texto: str) -> bool:
    """True se há um pedido de verdade; False para cumprimento e ruído.

    Conservadora de propósito: na dúvida, devolve True. Errar para "é pedido"
    custa uma chamada de IA; errar para "não é pedido" faz o bot ignorar o
    usuário, que é pior — e a regra permanente é SEMPRE responder.
    """
    if not texto:
        return False

    # Tira menção: "<@123> oi" é cumprimento, "<@123> cria um canal" não é.
    limpo = re.sub(r"<@!?\d+>", " ", texto)
    limpo = re.sub(r"@(everyone|here)", " ", limpo, flags=re.IGNORECASE)
    limpo = _sem_acento(limpo.strip())

    if not limpo or _VAZIO.match(limpo):
        return False
    return not _SAUDACAO.match(limpo)


def resposta_para_cumprimento(texto: str) -> str:
    """O que dizer quando não há pedido.

    Curta, sem título, sem rodapé, sem ruído interno — as regras permanentes de
    resposta. E pergunta o que a pessoa quer, porque "sempre responder" vale
    mesmo quando não há o que executar.
    """
    return "Oi. Diz o que você quer que eu faça no servidor."
