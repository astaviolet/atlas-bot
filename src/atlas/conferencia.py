"""Conferência factual da resposta do modelo contra o estado real.

POR QUE ISTO EXISTE
-------------------
Medido em produção, servidor real "Pinguim": pedido "quantos canais e cargos tem
esse servidor?", índice real no prompt (8 canais, 6 cargos), zero tool call, e a
modelo respondeu "11 canais e 10 cargos". Números inventados com a verdade na
frente dela.

Isso é exatamente o que a spec 185 proíbe ("resposta falsa") e o que o F5 já
tinha mostrado: instrução no prompt não segura. Então a conferência é em código.

O ESCOPO É ESTREITO DE PROPÓSITO
--------------------------------
Só confere contagem de canal/categoria/cargo — o que dá para verificar de forma
determinística contra o snapshot. Não tenta "verificar texto" em geral: corregir
prosa seria inventar de outro jeito. Se a modelo afirmar outra coisa errada,
este módulo não pega, e é melhor dizer isso do que fingir cobertura total.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

#: "11 canais", "10 cargos", "3 categorias" — com variação de acento e plural.
_CONTAGEM = re.compile(
    r"\b(\d{1,4})\s+(canais|canal|categorias|categoria|cargos|cargo)\b",
    re.IGNORECASE,
)

_SINONIMO = {
    "canal": "canais", "canais": "canais",
    "categoria": "categorias", "categorias": "categorias",
    "cargo": "cargos", "cargos": "cargos",
}


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def contagens_reais(snapshot: Any) -> dict[str, int]:
    """Quantidade real de cada coisa.

    CANAL TEM DUAS CONTAGENS LEGITIMAS e isso importa: o Discord lista categoria
    como canal (a API devolve 8 para o servidor Pinguim), mas o índice do prompt
    separa canal de categoria (7 + 1). As duas leituras são defensáveis, então
    `conferir_contagem` aceita qualquer uma — "corrigir" 8 para 7 seria eu
    introduzir um erro novo em cima de um que estou tentando tirar.
    """
    canais = list(getattr(snapshot, "channels", []) or [])
    categorias = [c for c in canais if getattr(c, "is_category", False)]
    return {
        "canais": len(canais) - len(categorias),
        "canais_com_categoria": len(canais),
        "categorias": len(categorias),
        "cargos": len(getattr(snapshot, "roles", []) or []),
    }


#: Leituras aceitas para cada palavra. Canal aceita as duas contagens.
_ACEITAS: dict[str, tuple[str, ...]] = {
    "canais": ("canais", "canais_com_categoria"),
    "categorias": ("categorias",),
    "cargos": ("cargos",),
}


def conferir_contagem(texto: str, snapshot: Any) -> tuple[str, list[str]]:
    """Corrige contagem que contradiz o estado real.

    Devolve `(texto_corrigido, divergencias)`. Lista vazia significa que nada
    contradizia — inclusive quando o texto não fala de contagem.
    """
    if snapshot is None or not texto:
        return texto, []

    reais = contagens_reais(snapshot)
    plano = _sem_acento(texto).lower()
    divergencias: list[str] = []
    novo = texto

    for numero, palavra in _CONTAGEM.findall(plano):
        chave = _SINONIMO.get(palavra)
        if chave is None or chave not in reais:
            continue
        dito = int(numero)
        aceitaveis = [reais[c] for c in _ACEITAS[chave]]
        if dito in aceitaveis:
            continue
        real = aceitaveis[0]

        divergencias.append(f"{chave}: a resposta dizia {dito}, o servidor tem {real}")
        # Troca só a primeira ocorrência deste número+palavra, para não reescrever
        # um "2" que apareça em outro contexto.
        novo = re.sub(
            rf"\b{numero}(\s+)(?:canais|canal|categorias|categoria|cargos|cargo)\b",
            lambda m, p=palavra, r=real: f"{r}{m.group(1)}{p}",
            novo,
            count=1,
            flags=re.IGNORECASE,
        )
    return novo, divergencias
