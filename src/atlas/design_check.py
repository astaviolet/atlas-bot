"""Checagem objetiva de qualidade de plano e de resultado (spec 24, 25, 47, 138).

O QUE ESTE MODULO FAZ E O QUE NAO FAZ
-------------------------------------
A auditoria (docs/AUDITORIA.md, achado 2.4) mediu que a doutrina de design no
prompt e IGNORADA pelos modelos gratuitos do pool: pediram "servidor tematico de
xadrez" e veio INFORMACOES/COMUNIDADE/VOZ, o template que a doutrina proibe.

Entao aqui so entra o que e OBJETIVO e da para decidir sem opiniao:

  - duplicata de nome
  - canal apontando para categoria que nao existe
  - cargo "estetico" carregando permissao administrativa
  - categoria vazia depois de executado
  - canal orfao depois de executado

O que NAO da para garantir em codigo: se o servidor e bonito, se o tema aparece,
se a nomenclatura e coerente. Isso continua dependendo do modelo. Fingir que um
validador resolve subjetividade seria exatamente o "sucesso falso" que a secao
185 proibe.

POR QUE O VALIDADOR PRE-EXECUCAO E QUASE VAZIO
----------------------------------------------
A primeira versao rejeitava o plano inteiro em tres casos. Dois eram errados:

  - "duplicata com o servidor": a Fase 3 ja reusa e devolve reused=True.
    Rejeitar transformava reuso benigno em erro duro.
  - "canal orfao": a spec 22/23 EXIGE sucesso parcial - se a operacao 7 de 10
    falha, 1-6 ficam feitas e o usuario recebe o relatorio. Rejeitar tudo antes
    destruia isso, e a tool ja falha por acao quando o pai nao existe.

Sobrou um caso que vale parar o plano: cargo novo nascendo com permissao
administrativa. Isso e politica, nao gosto.

O resto - categoria vazia, duplicata real, canal orfao - vai para o QA
POS-execucao, que e onde a spec 138 coloca mesmo.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from .models import CHANNEL_TYPE_LABEL, GuildSnapshot, Perm

#: Permissoes que nunca fazem sentido num cargo criado sem proposito funcional.
_ADMIN = (Perm.ADMINISTRATOR, Perm.MANAGE_GUILD, Perm.BAN_MEMBERS, Perm.KICK_MEMBERS)

log = logging.getLogger(__name__)

_CRIACAO = {"create_channel", "create_category", "create_role"}


def _norm(nome: Any) -> str:
    return str(nome or "").strip().casefold()


_POR_LABEL = {v.casefold(): k for k, v in CHANNEL_TYPE_LABEL.items()}


def _tipo_chave(bruto: Any) -> int | str:
    """Normaliza o tipo para comparar. Nunca levanta.

    O modelo manda "text"; a tool converte para 0. Aqui so interessa que o mesmo
    tipo caia na mesma chave - e um validador que estoura ValueError derruba o
    plano inteiro, que foi exatamente o bug da primeira versao.
    """
    if isinstance(bruto, int):
        return bruto
    texto = str(bruto or "").strip().casefold()
    if texto.isdigit():
        return int(texto)
    return _POR_LABEL.get(texto, texto)


# ---------------------------------------------------------------- antes de executar
def checar_plano(actions: Iterable[Any], snapshot: GuildSnapshot) -> list[str]:
    """Devolve a lista de problemas objetivos do plano. Vazia = plano limpo.

    Roda ANTES de qualquer chamada ao Discord: um plano ruim nao deve consumir
    rate limit para depois ser desfeito.
    """
    problemas: list[str] = []
    try:
        return _checar_plano(actions, snapshot)
    except Exception:  # noqa: BLE001 - validador quebrado nao pode virar outage
        log.exception("checagem de plano falhou; seguindo sem ela")
        return problemas


def _checar_plano(actions: Iterable[Any], snapshot: GuildSnapshot) -> list[str]:
    """So o que deve PARAR o plano. Ver docstring do modulo."""
    del snapshot  # hoje nao precisa do estado; fica na assinatura por simetria
    problemas: list[str] = []
    for acao in actions:
        tool = getattr(acao, "tool", "") or ""
        params = getattr(acao, "params", {}) or {}
        if tool != "create_role":
            continue
        perms = int(params.get("permissions") or 0)
        if any(perms & p.value for p in _ADMIN):
            problemas.append(
                f"cargo '{params.get('name')}' receberia permissao administrativa; "
                "cargo novo nao nasce com isso"
            )
    return problemas


# ---------------------------------------------------------------- depois de executar
def auditar_servidor(snapshot: GuildSnapshot) -> list[str]:
    """QA sobre o estado REAL do servidor, depois da execucao (spec 138).

    So defeitos objetivos. Nao opina sobre estetica.
    """
    problemas: list[str] = []

    categorias = [c for c in snapshot.channels if c.is_category]
    canais = [c for c in snapshot.channels if not c.is_category]
    ids = {c.id for c in snapshot.channels}

    for cat in categorias:
        filhos = [c for c in canais if c.parent_id == cat.id]
        if not filhos:
            problemas.append(f"a categoria '{cat.name}' esta vazia")

    for canal in canais:
        if canal.parent_id is not None and canal.parent_id not in ids:
            problemas.append(f"o canal '{canal.name}' aponta para uma categoria que nao existe")

    # mesmo nome + mesmo tipo + mesma categoria = duplicata real
    vistos: dict[tuple[str, int, Any], str] = {}
    for canal in canais:
        chave = (_norm(canal.name), canal.type, canal.parent_id)
        if chave in vistos:
            problemas.append(f"existem dois canais '{canal.name}' iguais na mesma categoria")
        vistos[chave] = canal.name

    nomes_categoria: dict[str, int] = {}
    for cat in categorias:
        nomes_categoria[_norm(cat.name)] = nomes_categoria.get(_norm(cat.name), 0) + 1
    for nome, qt in nomes_categoria.items():
        if qt > 1:
            problemas.append(f"existem {qt} categorias com o nome '{nome}'")

    return problemas
