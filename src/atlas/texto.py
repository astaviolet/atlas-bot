"""Limpeza do texto que vai para o Discord.

Regra do projeto: formatacao se impoe no codigo, nao no prompt. O modelo ja
devolveu texto com espaco invisivel (U+202F), hifen invisivel (U+2011), aspas
curvas, travessao, check `✓` e tabela markdown de 1700 caracteres. Pedir
"seja breve" no prompt reduz, mas nao garante - entao a saida passa por aqui
sempre, venha de onde vier.

Nao ha dependencia de outros modulos do projeto de proposito: embeds.py
precisa importar isto, e formatting.py importa embeds.py.
"""

from __future__ import annotations

import re
import unicodedata

#: Limite de caracteres da resposta. O usuario pediu o mais direto possivel.
#: 220 cabe uma frase completa e o essencial; o resto ele pergunta se quiser.
MAX_DESCRICAO = 220

# ---------------------------------------------------------------------------
# Substituicoes de caractere
# ---------------------------------------------------------------------------

#: Invisiveis e de largura zero: some com eles.
_REMOVER = "".join(
    [
        "\u200b",  # zero width space
        "\u200c",  # zero width non-joiner
        "\u200d",  # zero width joiner
        "\u2060",  # word joiner
        "\ufeff",  # bom / zero width no-break space
        "\u00ad",  # soft hyphen
        "\u180e",  # mongolian vowel separator
    ]
)

#: Mapa de "parecido com ASCII mas nao e".
_TROCAR = {
    "\u00a0": " ",   # no-break space
    "\u202f": " ",   # narrow no-break space  <- apareceu em "ID\u202f1551..."
    "\u2009": " ",   # thin space
    "\u200a": " ",   # hair space
    "\u2007": " ",   # figure space
    "\u2010": "-",   # hyphen
    "\u2011": "-",   # non-breaking hyphen     <- apareceu em "conectar-se"
    "\u2012": "-",   # figure dash
    "\u2013": "-",   # en dash
    "\u2014": "-",   # em dash                 <- travessao
    "\u2015": "-",   # horizontal bar
    "\u2018": "'",   # left single quote
    "\u2019": "'",   # right single quote
    "\u201a": "'",
    "\u201b": "'",
    "\u201c": '"',   # left double quote       <- aspas curvas
    "\u201d": '"',   # right double quote
    "\u201e": '"',
    "\u201f": '"',
    "\u2026": "...", # ellipsis
    "\u2022": "-",   # bullet
    "\u2027": "-",
    "\u00b7": "-",   # middle dot usado como bullet
    "\u2043": "-",   # hyphen bullet
    "\u2212": "-",   # minus sign
    "\u2713": "",    # check mark              <- o `✓` do checklist
    "\u2714": "",
    "\u2715": "",
    "\u2716": "",
    "\u2717": "",
    "\u2718": "",
    "\u2192": "->",  # rightwards arrow
    "\u2190": "<-",
    "\u25cf": "-",
    "\u25cb": "-",
    "\u2611": "",
    "\u2610": "",
}

_BACKTICK = re.compile(r"`+")
_HEADER = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_LINHA_TABELA = re.compile(r"^\s*\|.*\|\s*$")
_SEPARADOR_TABELA = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_ESPACOS_SEGUIDOS = re.compile(r"[ \t]{2,}")
_LINHAS_VAZIAS = re.compile(r"\n{3,}")

# ---------------------------------------------------------------------------
# Marcadores de controle que o modelo vaza
# ---------------------------------------------------------------------------
# Alguns modelos gratuitos sao treinados com frameworks de agente que usam
# marcadores de fim de turno. O modelo emitiu "<CPA_DONE>" no meio da resposta
# e foi direto para o usuario. Nao da para confiar que o modelo vai parar de
# emitir, entao a saida filtra.
_MARCADOR_TAG = re.compile(r"</?[A-Z][A-Z0-9_]{2,}\s*/?>")          # <CPA_DONE>
_MARCADOR_PIPE = re.compile(r"<\|[^|>]{1,40}\|>")                   # <|end_of_turn|>
_MARCADOR_LINHA = re.compile(r"^\s*(?:\[|<)(?:/)?(?:SYSTEM|ASSISTANT|TOOL|FUNCTION|OBSERVATION|HUMAN)(?:\]|>)\s*$", re.MULTILINE | re.IGNORECASE)
_MARCADOR_BLOCO = re.compile(
    r"<(?:function_calls|antml:[a-z_]+|thinking|tool_call|response)[^>]*>.*?"
    r"</(?:function_calls|antml:[a-z_]+|thinking|tool_call|response)>",
    re.DOTALL | re.IGNORECASE,
)


def _troca_char(txt: str) -> str:
    for alvo in _REMOVER:
        txt = txt.replace(alvo, "")
    for velho, novo in _TROCAR.items():
        txt = txt.replace(velho, novo)
    # Qualquer outro caractere de formato/controle que eu nao tenha listado.
    txt = "".join(
        c for c in txt
        if unicodedata.category(c)[0] not in ("C",) or c in "\n\t"
    )
    return txt


def _tabela_vira_linhas(txt: str) -> str:
    """Tabela markdown vira texto corrido.

    Tabela em embed de Discord fica ilegivel no celular e ocupa dezenas de
    linhas. Cada linha vira "cabecalho: valor" para as colunas relevantes.
    """
    linhas = txt.split("\n")
    if not any(_LINHA_TABELA.match(l) for l in linhas):
        return txt

    saida: list[str] = []
    cabecalho: list[str] = []
    for linha in linhas:
        if not _LINHA_TABELA.match(linha):
            if cabecalho and linha.strip():
                saida.append(linha)
            elif not linha.strip():
                saida.append("")
            else:
                saida.append(linha)
            continue
        celulas = [c.strip() for c in linha.strip().strip("|").split("|")]
        if _SEPARADOR_TABELA.match(linha):
            continue
        if not cabecalho:
            cabecalho = celulas
            continue
        if len(celulas) == 1:
            saida.append(celulas[0])
            continue
        partes = []
        for nome, valor in zip(cabecalho, celulas):
            if valor and valor != "-":
                partes.append(f"{nome}: {valor}" if nome else valor)
        if partes:
            saida.append("; ".join(partes))
    return "\n".join(saida)


def _corta_em_frase(txt: str, limite: int) -> str:
    """Corta no limite, mas numa fronteira de frase em vez de no meio da palavra."""
    if len(txt) <= limite:
        return txt
    janela = txt[:limite]
    # procura o ultimo fim de frase
    for sep in ("\n\n", ". ", "! ", "? ", "\n", ", "):
        pos = janela.rfind(sep)
        if pos >= limite * 0.55:
            return janela[:pos].rstrip() + " (...)"
    return janela.rstrip() + " (...)"


def tirar_marcadores(txt: str) -> str:
    """Remove marcador de controle que o modelo vazou.

    Caso real: o modelo devolveu a resposta seguida de "<CPA_DONE>", que foi
    direto para o usuario.
    """
    txt = _MARCADOR_BLOCO.sub("", txt)
    txt = _MARCADOR_PIPE.sub("", txt)
    txt = _MARCADOR_TAG.sub("", txt)
    txt = _MARCADOR_LINHA.sub("", txt)
    return txt


_MENCIONAR_TODOS = re.compile(r"(?<!\\)@(everyone|here)\b", re.IGNORECASE)
_MENCIONAR_ALVO = re.compile(r"(?<!\\)<@(?![#])([!&]?\d{15,25})>")


def desarmar_mencoes(txt: str) -> str:
    """Impede que o texto do bot pingue alguem.

    Regra do projeto: nunca mencionar @everyone, @here ou cargo de verdade.
    Citar tudo bem; disparar notificacao para o servidor inteiro, nao.

    A barra invertida na frente faz o Discord mostrar o texto literal sem
    resolver a mencao - e nao introduz caractere invisivel.
    """
    txt = _MENCIONAR_TODOS.sub(r"\@\1", txt)
    txt = _MENCIONAR_ALVO.sub(r"\<@\1>", txt)
    return txt


#: Assinaturas do prompt de sistema em vigor. Preenchido por
#: `registrar_assinaturas_internas`, que o bot chama ao montar o prompt.
_ASSINATURAS_INTERNAS: list[str] = []


def registrar_assinaturas_internas(prompt: str) -> int:
    """Guarda as assinaturas do prompt atual para `limpar` filtrar vazamento.

    Spec 112 em código: `policy.py` barra o pedido de injection na entrada, mas
    nada impedia o modelo de devolver o prompt na resposta. Pedir para o modelo
    "não revelar as regras" dentro do próprio prompt é pedir para a fechadura
    ficar do lado de fora.
    """
    from .antivazamento import assinaturas_internas

    global _ASSINATURAS_INTERNAS
    _ASSINATURAS_INTERNAS = assinaturas_internas(prompt)
    return len(_ASSINATURAS_INTERNAS)


def limpar(texto: str, *, limite: int = MAX_DESCRICAO) -> str:
    """Passa o texto por tudo: marcador vazado, caracteres, markdown pesado, tamanho."""
    if not texto:
        return texto
    # Vazamento primeiro: remover caractere exótico antes poderia separar as
    # palavras da assinatura e o filtro deixaria passar.
    if _ASSINATURAS_INTERNAS:
        from .antivazamento import filtrar

        texto, _removidos = filtrar(texto, _ASSINATURAS_INTERNAS)
    txt = tirar_marcadores(texto)
    txt = _troca_char(txt)
    txt = _tabela_vira_linhas(txt)
    txt = _BACKTICK.sub("", txt)
    txt = _HEADER.sub("", txt)
    txt = desarmar_mencoes(txt)
    txt = _ESPACOS_SEGUIDOS.sub(" ", txt)
    txt = _LINHAS_VAZIAS.sub("\n\n", txt)
    txt = txt.replace(" \n", "\n").strip()
    return _corta_em_frase(txt, limite)
