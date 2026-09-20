"""Reforma de servidor existente (spec 45, 46, 84, 85).

A DIFERENÇA ENTRE CONSTRUIR E REFORMAR
--------------------------------------
`design_system.projetar()` parte do zero. Aqui o servidor já existe, tem nome,
tem histórico, tem gente dentro. A spec 46 é explícita: "preservar conteúdo
importante. Não apagar tudo por padrão."

Então a regra que governa este módulo é: **reformar é reaproveitar.** O plano
preferido é renomear e mover o que já existe, não excluir e recriar. Excluir é o
último recurso, e nunca entra no plano sozinho — vai para `suspeitas`, que exige
decisão humana.

POR QUE ISSO NÃO É SÓ PREFERÊNCIA ESTÉTICA
------------------------------------------
Excluir e recriar um canal destrói o histórico dele. Mensagens, threads e
configuração somem, e não há rollback para isso — o snapshot da Fase 8 guarda
estrutura, não conteúdo. Então "delete + create" é a única operação deste
sistema que é destrutiva de verdade e irreversível. Tratá-la como caminho
padrão seria o erro mais caro possível.

ORDEM DA SPEC 84
----------------
AUDITAR → MAPEAR → PLANEJAR → MOSTRAR IMPACTO → CONFIRMAR → EXECUTAR → VERIFICAR

Este módulo faz até MOSTRAR IMPACTO. Não executa nada — quem executa é o
executor de sempre, com as mesmas barreiras de policy, dependência e
confirmação. Plano ≠ execução (spec 11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .design_check import auditar_servidor
from .design_system import Arquitetura, Briefing, Nomenclatura, projetar
from .models import GuildSnapshot

#: Nomes que indicam canal padrão do Discord ou de chegada. Não são "lixo":
#: são o que a pessoa vê primeiro, e a reforma deve acomodá-los, não apagá-los.
_NOMES_PADRAO = {
    "general", "geral", "welcome", "bem-vindo", "boas-vindas", "regras",
    "rules", "announcements", "anuncios", "anúncios",
}


def _norm(nome: Any) -> str:
    """Normaliza para comparar. Caixa, espaço e separador de emoji não são
    diferença de identidade — são diferença de nomenclatura."""
    s = str(nome or "").strip().lower()
    for sep in ("・", "「", "」", "·", "•", "|", "-", "—", "_"):
        s = s.replace(sep, " ")
    # remove emoji e símbolos não-alfanuméricos do começo
    s = "".join(ch for ch in s if ch.isalnum() or ch == " ").strip()
    return " ".join(s.split())


#: Sinônimos. Sem isto a reforma casa só por nome exato e trata "chat" e
#: "bate-papo" como canais diferentes: cria um novo e marca o antigo como sobra.
#: O resultado é o servidor crescer em vez de se organizar — que é exatamente o
#: defeito que reformar existe para corrigir.
_SINONIMOS: dict[str, str] = {
    "chat": "bate papo", "conversa": "bate papo", "conversas": "bate papo",
    "geral": "bate papo", "general": "bate papo", "papo": "bate papo",
    "avisos": "anuncios", "novidades": "anuncios", "announcement": "anuncios",
    "announcements": "anuncios", "rules": "regras",
    "welcome": "boas vindas", "bem vindo": "boas vindas",
    "bem-vindo": "boas vindas", "chegada": "boas vindas",
    "duvidas": "dúvidas", "ajuda": "dúvidas", "suporte": "dúvidas",
    "lfg": "lfg", "procurando grupo": "lfg",
    "voice": "sala geral", "voz": "sala geral", "call": "sala geral",
}


def _chave(nome: Any) -> str:
    """Nome normalizado + sinônimo. É por isto que a reforma casa canais."""
    n = _norm(nome)
    return _SINONIMOS.get(n, n)


def _tem_emoji(nome: Any) -> bool:
    return any(ord(ch) > 0x2100 for ch in str(nome or ""))


@dataclass
class Achado:
    """Um problema encontrado na auditoria, com o que fazer a respeito."""

    problema: str
    severidade: str = "aviso"  # "aviso" | "critico"
    #: Canal/cargo envolvido, quando há.
    alvo: str = ""


@dataclass
class AcaoDeReforma:
    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    motivo: str = ""


@dataclass
class Reforma:
    briefing: Briefing
    achados: list[Achado] = field(default_factory=list)
    #: O que já existe e continua valendo, só ajustado.
    renomear: list[AcaoDeReforma] = field(default_factory=list)
    mover: list[AcaoDeReforma] = field(default_factory=list)
    criar: list[AcaoDeReforma] = field(default_factory=list)
    #: O que PARECE sobra. Nunca vai para o plano automaticamente.
    suspeitas: list[str] = field(default_factory=list)

    @property
    def acoes(self) -> list[AcaoDeReforma]:
        """Plano de reforma. Repare na ausência de delete: spec 46."""
        return [*self.renomear, *self.mover, *self.criar]

    @property
    def tem_destrutivo(self) -> bool:
        """Sempre False por construção. Existe para o chamador não ter que
        confiar neste comentário — se um dia alguém adicionar delete, este
        property passa a dizer a verdade e os testes pegam."""
        return any(a.tool.startswith("delete_") for a in self.acoes)

    def impacto(self) -> str:
        """Spec 84: MOSTRAR IMPACTO. E spec 12: dry run legível."""
        linhas = [
            f"Renomeados: {len(self.renomear)}",
            f"Movidos: {len(self.mover)}",
            f"Criados: {len(self.criar)}",
            "Excluídos: 0 (nada é excluído sem decisão sua)",
        ]
        if self.suspeitas:
            linhas.append(
                f"Possíveis sobras para você decidir: {len(self.suspeitas)}"
            )
        return "\n".join(linhas)


def auditar(snapshot: GuildSnapshot) -> list[Achado]:
    """Auditoria da spec 45. Cobre o que `design_check.auditar_servidor` cobre
    (defeitos objetivos) e acrescenta o que ele não olha: nomenclatura mista e
    cargos.

    Não duplica de propósito — chama a função existente e soma.
    """
    achados: list[Achado] = []

    for p in auditar_servidor(snapshot):
        achados.append(Achado(problema=p, severidade="critico"))

    canais = [c for c in snapshot.channels if not c.is_category]

    # ---- nomenclatura mista (spec 36)
    com_emoji = sum(1 for c in canais if _tem_emoji(c.name))
    if canais and 0 < com_emoji < len(canais):
        achados.append(Achado(
            problema=(
                f"nomenclatura mista: {com_emoji} de {len(canais)} canais usam "
                "emoji e o resto não"
            ),
            severidade="aviso",
        ))

    # ---- categorias demais para o tanto de canal (spec 79)
    categorias = [c for c in snapshot.channels if c.is_category]
    if len(categorias) >= 5 and canais and len(canais) / len(categorias) < 1.5:
        achados.append(Achado(
            problema=(
                f"{len(categorias)} categorias para {len(canais)} canais: "
                "área demais para o conteúdo que existe"
            ),
            severidade="aviso",
        ))

    # ---- cargos: administrativos demais (spec 42)
    admin = [
        r for r in snapshot.roles
        if getattr(r, "permissions", 0) & 0x8  # ADMINISTRATOR
        and not getattr(r, "managed", False)
    ]
    if len(admin) > 3:
        achados.append(Achado(
            problema=f"{len(admin)} cargos com permissão de administrador",
            severidade="critico",
        ))

    return achados


def planejar_reforma(
    snapshot: GuildSnapshot,
    briefing: Briefing,
    *,
    n_membros: int | None = None,
) -> Reforma:
    """Audita o servidor real e monta um plano que reaproveita o que existe.

    O alvo vem de `design_system.projetar` — a mesma composição de domínio ×
    porte × público × estilo. A diferença é que aqui cada canal do alvo é
    casado com um canal que já existe antes de cogitar criar.
    """
    reforma = Reforma(briefing=briefing, achados=auditar(snapshot))

    alvo: Arquitetura = projetar(briefing)
    existentes = [c for c in snapshot.channels if not c.is_category]
    categorias_existentes = {
        _norm(c.name): c for c in snapshot.channels if c.is_category
    }

    usados: set[int] = set()

    for cat_alvo in alvo.categorias:
        # categoria: reaproveita por nome, senão cria
        cat_existente = categorias_existentes.get(_norm(cat_alvo.nome))
        if cat_existente is None:
            cat_existente = next(
                (c for c in snapshot.channels
                 if c.is_category and _chave(c.name) == _chave(cat_alvo.nome)),
                None,
            )
        if cat_existente is None:
            reforma.criar.append(AcaoDeReforma(
                tool="create_category",
                params={"name": cat_alvo.nome},
                motivo=f"área '{cat_alvo.proposito}' não existe no servidor",
            ))
            cat_id: Any = None  # o executor resolve o id real depois
        else:
            cat_id = cat_existente.id
            if str(cat_existente.name) != cat_alvo.nome:
                reforma.renomear.append(AcaoDeReforma(
                    tool="edit_category",
                    params={"category_id": cat_existente.id, "name": cat_alvo.nome},
                    motivo="nomenclatura fora do padrão do servidor",
                ))

        for canal_alvo in cat_alvo.canais:
            # casa por nome normalizado: é assim que '📢・anuncios' casa com
            # 'anuncios' em vez de virar canal novo.
            # Dois passes, e o motivo importa. Com um passe so, a ordem da lista
            # decidia: num servidor com 'general' E 'chat', 'general' aparecia
            # primeiro e era consumido como 'bate-papo', sobrando justamente o
            # canal que era o chat. Canal padrao do Discord fica preservado como
            # esta (spec 46); quem se reorganiza e o resto.
            alvo_chave = _chave(canal_alvo.nome)
            achado = next(
                (c for c in existentes
                 if c.id not in usados and _norm(c.name) == _norm(canal_alvo.nome)),
                None,
            )
            if achado is None:
                achado = next(
                    (c for c in existentes
                     if c.id not in usados
                     and _norm(c.name) not in _NOMES_PADRAO
                     and _chave(c.name) == alvo_chave),
                    None,
                )
            if achado is None:
                reforma.criar.append(AcaoDeReforma(
                    tool="create_channel",
                    params={
                        "name": canal_alvo.nome,
                        "type": canal_alvo.tipo,
                        **({"category_id": cat_id} if cat_id is not None else {}),
                    },
                    motivo=canal_alvo.proposito,
                ))
                continue

            usados.add(achado.id)
            if str(achado.name) != canal_alvo.nome:
                reforma.renomear.append(AcaoDeReforma(
                    tool="edit_channel",
                    params={"channel_id": achado.id, "name": canal_alvo.nome},
                    motivo="nomenclatura fora do padrão do servidor",
                ))
            if cat_id is not None and achado.parent_id != cat_id:
                reforma.mover.append(AcaoDeReforma(
                    tool="move_channel",
                    params={"channel_id": achado.id, "category_id": cat_id},
                    motivo=f"canal pertence à área '{cat_alvo.proposito}'",
                ))

    # ---- o que sobrou: suspeita, nunca exclusão automática
    for c in existentes:
        if c.id in usados:
            continue
        if _norm(c.name) in _NOMES_PADRAO:
            continue  # canal de chegada fica, mesmo fora do alvo
        reforma.suspeitas.append(c.name)

    return reforma


def nomenclatura_dominante(snapshot: GuildSnapshot) -> Nomenclatura:
    """Detecta o estilo que o servidor já usa, para a reforma seguir em vez de
    impor outro (spec 46: preservar).

    Sem canal com emoji, devolve LIMPO — que é o que o servidor já é.
    """
    nomes = [str(c.name) for c in snapshot.channels if not c.is_category]
    if not nomes:
        return Nomenclatura.LIMPO
    com_emoji = [n for n in nomes if _tem_emoji(n)]
    if len(com_emoji) * 2 < len(nomes):
        return Nomenclatura.LIMPO
    if any("・" in n for n in com_emoji):
        return Nomenclatura.SEPARADOR_PONTO
    if any("「" in n for n in com_emoji):
        return Nomenclatura.COLCHETE
    if any("-" in n for n in com_emoji):
        return Nomenclatura.TRACO
    return Nomenclatura.LIMPO
