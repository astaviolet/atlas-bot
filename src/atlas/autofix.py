"""Auto-correcção pós-verificação (spec 25).

QUANDO ISTO RODA
----------------
Uma ação falhou por um motivo que o próprio sistema sabe consertar. Em vez de
devolver o erro pro usuário e esperar ele reformular, corrige o parâmetro e
tenta de novo — **uma** vez. Se falhar outra vez, o erro vai pro usuário como
iria antes.

A REGRA QUE NAO PODE SER QUEBRADA
---------------------------------
Auto-correção **corrige**, nunca **inventa**. Cortar um nome longo é correção.
Criar um nome porque veio vazio é invenção — e invenção é exatamente o que a
spec 185 proíbe. Por isso `nome vazio`, `category_id inexistente` e afins ficam
de fora: não há valor correto a deduzir, só a adivinhar.

Toda correção é auditada com o antes e o depois. Correção silenciosa é
indistinguível de bug.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

#: Alias que o modelo manda e o Discord não aceita. Só sinônimos inequívocos:
#: se houver dúvida, é melhor falhar do que escolher por ele.
_TIPOS = {
    "texto": "text", "textual": "text", "chat": "text",
    "voz": "voice", "audio": "voice", "áudio": "voice",
    "anuncio": "announcement", "anúncio": "announcement", "news": "announcement",
    "forum": "forum", "fórum": "forum",
    "categoria": "category",
}

#: Erros que NÃO têm correção honesta. Listados de propósito: se alguém acrescentar
#: uma regra aqui, precisa justificar por que não é invenção.
_SEM_CORRECAO = {
    "nome vazio",
    "use create_category",
    "category_id invalido",
    "channel_id invalido",
}


def _truncar(texto: Any, limite: int) -> str:
    s = str(texto)
    if len(s) <= limite:
        return s
    # corta em limite-1 e poe reticencia: o usuario ve que foi cortado
    return s[: max(1, limite - 1)].rstrip() + "…"


def corrigir(
    motivo: str,
    params: dict[str, Any],
    *,
    max_name_len: int = 100,
    max_topic_len: int = 1024,
) -> dict[str, Any] | None:
    """Devolve params corrigidos, ou None se não há correção honesta.

    Nunca muta o dict recebido: quem chama precisa do original para auditar o
    antes/depois.
    """
    motivo = (motivo or "").strip()
    if motivo in _SEM_CORRECAO:
        return None
    if not isinstance(params, dict) or not params:
        return None

    novo = dict(params)
    mudou = False

    if motivo == "nome longo" and "name" in novo:
        novo["name"] = _truncar(novo["name"], max_name_len)
        mudou = novo["name"] != params["name"]

    elif motivo == "topico longo" and "topic" in novo:
        novo["topic"] = _truncar(novo["topic"], max_topic_len)
        mudou = novo["topic"] != params["topic"]

    elif motivo == "slowmode fora da faixa" and "slowmode" in novo:
        try:
            valor = int(novo["slowmode"])
        except (TypeError, ValueError):
            return None
        novo["slowmode"] = max(0, min(21600, valor))
        mudou = novo["slowmode"] != valor

    elif motivo == "tipo de canal invalido" and "type" in novo:
        bruto = str(novo["type"]).strip().lower()
        if bruto in _TIPOS:
            novo["type"] = _TIPOS[bruto]
            mudou = True

    elif motivo == "voz nao aceita nsfw" and novo.get("nsfw"):
        novo.pop("nsfw", None)
        mudou = True

    elif motivo == "tipo invalido" and "type" in novo:
        bruto = str(novo["type"]).strip().lower()
        if bruto in _TIPOS:
            novo["type"] = _TIPOS[bruto]
            mudou = True

    return novo if mudou else None


def diferenca(antes: dict[str, Any], depois: dict[str, Any]) -> dict[str, Any]:
    """Só os campos que mudaram, para o log de auditoria não carregar o plano todo."""
    return {
        k: {"antes": antes.get(k), "depois": depois.get(k)}
        for k in set(antes) | set(depois)
        if antes.get(k) != depois.get(k)
    }
