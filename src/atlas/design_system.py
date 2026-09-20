"""Sistema de design de servidores (spec 26-47, 78, 135-138).

A REGRA QUE DEFINE ESTE MÓDULO
------------------------------
Spec 27/79: servidores diferentes não podem parecer iguais. Spec 78: não pode
existir "template Fortnite fixo". Spec 169: se eu tirar o nome do jogo, ainda
tem que dar para perceber que cada servidor foi projetado para uma finalidade
diferente.

Então **não há template por tema**. O que há é composição:

    ARQUITETURA = domínio (o que a comunidade faz)
                × porte (quantas pessoas)
                × público (competitivo, casual, profissional)
                × estilo visual (como se chama e como se escreve)

O tema entra só no vocabulário (nome dos canais de identidade), nunca na
estrutura. É por isso que "servidor de Fortnite" e "servidor de Valorant" com o
mesmo porte e público saem estruturalmente parecidos — e isso está certo: os dois
são gaming competitivo. O que muda é o vocabulário. E "Fortnite competitivo" vs
"Fortnite casual" saem diferentes, porque o público mudou a estrutura.

POR QUE ISTO É CÓDIGO E NÃO PROMPT
----------------------------------
Medido na Fase 5: a doutrina de design estava no prompt (647 tokens) e o modelo
devolveu o template genérico proibido, duplicou canais e não criou cargos.
Prompt não segura qualidade de design com pool gratuito. Aqui a estrutura é
gerada por composição determinística e testável; o modelo escolhe o briefing, o
código projeta.

ESCALA (spec 44)
----------------
"Não criar 100 canais para 20 membros." O porte corta a arquitetura: comunidade
pequena recebe menos categorias e canais combinados. Isso não é cosmético — é o
que impede o servidor de nascer morto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Porte(str, Enum):
    """Spec 44. Definido por número de membros, não por opinião."""

    PEQUENO = "pequeno"
    MEDIO = "medio"
    GRANDE = "grande"


class Dominio(str, Enum):
    """O que a comunidade faz. É o eixo que mais muda a estrutura."""

    GAMING_COMPETITIVO = "gaming_competitivo"
    GAMING_CASUAL = "gaming_casual"
    RP = "rp"
    CRIADOR = "criador"
    LOJA = "loja"
    SAAS = "saas"
    EDUCACAO = "educacao"
    CLA = "cla"
    COMUNIDADE = "comunidade"


class EstiloVisual(str, Enum):
    """Spec 35. Muda nomenclatura e vocabulário, nunca a estrutura."""

    CLEAN = "clean"
    PREMIUM = "premium"
    COMPETITIVO = "competitivo"
    FUTURISTA = "futurista"
    CYBERPUNK = "cyberpunk"
    MILITAR = "militar"
    MEDIEVAL = "medieval"
    ANIME = "anime"
    MINIMALISTA = "minimalista"
    CASUAL = "casual"
    PROFISSIONAL = "profissional"
    GAMER = "gamer"
    DARK = "dark"


class Nomenclatura(str, Enum):
    """Spec 36: uma linguagem só por servidor. Misturar estilo é o defeito mais
    visível de servidor montado por template."""

    SEPARADOR_PONTO = "ponto"        # 📢・anuncios
    COLCHETE = "colchete"            # 「📢」anuncios
    TRACO = "traco"                  # 📢-anuncios
    LIMPO = "limpo"                  # anuncios


class Publico(str, Enum):
    COMPETITIVO = "competitivo"
    CASUAL = "casual"
    PROFISSIONAL = "profissional"
    MISTO = "misto"


#: Vocabulário por estilo. Só nomes e separador — estrutura vem do domínio.
_ESTILO: dict[EstiloVisual, dict[str, str]] = {
    EstiloVisual.CLEAN: {"nomenclatura": Nomenclatura.LIMPO, "tom": "direto"},
    EstiloVisual.PREMIUM: {"nomenclatura": Nomenclatura.SEPARADOR_PONTO, "tom": "sofisticado"},
    EstiloVisual.COMPETITIVO: {"nomenclatura": Nomenclatura.COLCHETE, "tom": "incisivo"},
    EstiloVisual.FUTURISTA: {"nomenclatura": Nomenclatura.COLCHETE, "tom": "técnico"},
    EstiloVisual.CYBERPUNK: {"nomenclatura": Nomenclatura.COLCHETE, "tom": "urbano"},
    EstiloVisual.MILITAR: {"nomenclatura": Nomenclatura.TRACO, "tom": "hierárquico"},
    EstiloVisual.MEDIEVAL: {"nomenclatura": Nomenclatura.SEPARADOR_PONTO, "tom": "solene"},
    EstiloVisual.ANIME: {"nomenclatura": Nomenclatura.SEPARADOR_PONTO, "tom": "expressivo"},
    EstiloVisual.MINIMALISTA: {"nomenclatura": Nomenclatura.LIMPO, "tom": "enxuto"},
    EstiloVisual.CASUAL: {"nomenclatura": Nomenclatura.TRACO, "tom": "solto"},
    EstiloVisual.PROFISSIONAL: {"nomenclatura": Nomenclatura.LIMPO, "tom": "formal"},
    EstiloVisual.GAMER: {"nomenclatura": Nomenclatura.SEPARADOR_PONTO, "tom": "energético"},
    EstiloVisual.DARK: {"nomenclatura": Nomenclatura.COLCHETE, "tom": "sombrio"},
}

_EMOJI = {
    "anuncios": "📢", "regras": "📜", "boas-vindas": "👋", "bate-papo": "💬",
    "avisos": "🔔", "suporte": "🛟", "novidades": "✨", "lfg": "🎮",
    "competitivo": "🏆", "resultados": "📊", "recrutamento": "📝",
    "clipes": "🎬", "conquistas": "🥇", "voz": "🔊", "afk": "💤",
    "equipe": "🛡️", "log": "📋", "feedback": "💭", "ideias": "💡",
    "apresente-se": "🙋", "cargos": "🎭", "dúvidas": "❓",
}


@dataclass
class Briefing:
    """Spec 135: o que define um servidor antes de qualquer canal existir."""

    tema: str = ""
    dominio: Dominio = Dominio.COMUNIDADE
    porte: Porte = Porte.MEDIO
    estilo: EstiloVisual = EstiloVisual.CLEAN
    publico: Publico = Publico.MISTO

    def assinatura(self) -> str:
        """Dois briefings com a mesma assinatura produzem a mesma estrutura.
        Serve de prova nos testes de que o tema sozinho não muda a arquitetura."""
        return f"{self.dominio.value}|{self.porte.value}|{self.publico.value}|{self.estilo.value}"


@dataclass
class ProjetoCanal:
    nome: str
    tipo: str = "text"
    proposito: str = ""
    privado: bool = False

    def tem_funcao(self) -> bool:
        """Spec 38: canal sem função clara não deveria ter sido criado."""
        return bool(self.proposito.strip())


@dataclass
class ProjetoCategoria:
    nome: str
    proposito: str
    canais: list[ProjetoCanal] = field(default_factory=list)


@dataclass
class ProjetoCargo:
    nome: str
    tipo: str  # "funcional" ou "identidade" (spec 40)
    posicao: int = 0
    cor: int = 0
    permissoes: list[str] = field(default_factory=list)


@dataclass
class Arquitetura:
    briefing: Briefing
    categorias: list[ProjetoCategoria] = field(default_factory=list)
    cargos: list[ProjetoCargo] = field(default_factory=list)
    onboarding: list[str] = field(default_factory=list)

    @property
    def total_canais(self) -> int:
        return sum(len(c.canais) for c in self.categorias)

    def nomes_de_canal(self) -> list[str]:
        return [c.nome for cat in self.categorias for c in cat.canais]


# --------------------------------------------------------------------- inferência
_POR_TEXTO: list[tuple[tuple[str, ...], Dominio]] = [
    (("rp", "roleplay", "gta rp", "cidade"), Dominio.RP),
    (("clã", "cla", "guild", "esquadrão", "esquadrao"), Dominio.CLA),
    (("competitivo", "ranked", "torneio", "esports", "campeonato"), Dominio.GAMING_COMPETITIVO),
    (("loja", "venda", "produto", "pedido", "cliente"), Dominio.LOJA),
    (("saas", "app", "software", "api", "startup", "produto digital"), Dominio.SAAS),
    (("curso", "escola", "aula", "aluno", "estudo", "educação", "educacao"), Dominio.EDUCACAO),
    (("criador", "streamer", "youtube", "twitch", "conteúdo", "conteudo", "canal"),
     Dominio.CRIADOR),
    (("fortnite", "valorant", "minecraft", "cs", "lol", "jogo", "gamer", "games"),
     Dominio.GAMING_CASUAL),
]


def inferir_dominio(texto: str) -> Dominio:
    """Domínio pelo pedido. Sem chute: se nada bate, COMUNIDADE."""
    baixo = (texto or "").lower()
    for palavras, dominio in _POR_TEXTO:
        if any(p in baixo for p in palavras):
            return dominio
    return Dominio.COMUNIDADE


def inferir_porte(n_membros: int | None) -> Porte:
    """Spec 44. Limiares conservadores de propósito: errar para baixo cria menos
    canal inútil, errar para cima cria servidor morto."""
    if n_membros is None:
        return Porte.MEDIO
    if n_membros < 50:
        return Porte.PEQUENO
    if n_membros < 300:
        return Porte.MEDIO
    return Porte.GRANDE


def inferir_estilo(texto: str) -> EstiloVisual:
    baixo = (texto or "").lower()
    for nome in EstiloVisual:
        if nome.value in baixo:
            return nome
    if any(p in baixo for p in ("competitivo", "ranked", "torneio")):
        return EstiloVisual.COMPETITIVO
    if any(p in baixo for p in ("premium", "profissional", "sério", "serio")):
        return EstiloVisual.PREMIUM
    return EstiloVisual.CLEAN


# ----------------------------------------------------------------------- projeto
def _n(briefing: Briefing, chave: str) -> str:
    """Aplica a nomenclatura do estilo. Uma linguagem só (spec 36)."""
    base = chave.lower()
    if briefing.estilo in (EstiloVisual.MINIMALISTA, EstiloVisual.CLEAN,
                           EstiloVisual.PROFISSIONAL):
        return base
    emoji = _EMOJI.get(base, "")
    nomen = Nomenclatura(_ESTILO[briefing.estilo]["nomenclatura"])
    if nomen == Nomenclatura.LIMPO:
        return base
    # Sem emoji cadastrado o formato continua o mesmo, so sem o simbolo. Cair no
    # nome puro aqui deixaria o servidor com nomenclatura mista - que e
    # exatamente o que a spec 36 proibe e o defeito mais visivel de servidor
    # montado por template.
    if nomen == Nomenclatura.SEPARADOR_PONTO:
        return f"{emoji}・{base}" if emoji else f"・{base}"
    if nomen == Nomenclatura.COLCHETE:
        return f"「{emoji}」{base}" if emoji else f"「{base}」"
    return f"{emoji}-{base}" if emoji else f"-{base}"


#: Estrutura por domínio. São ÁREAS CONCEITUAIS (spec 37) com o propósito de cada
#: canal — não uma lista de nomes decorativos.
_BASE: dict[Dominio, list[tuple[str, str, list[tuple[str, str, str]]]]] = {
    # (categoria, propósito, [(canal, tipo, propósito)])
    Dominio.GAMING_COMPETITIVO: [
        ("início", "chegar, entender e entrar", [
            ("boas-vindas", "text", "primeira coisa que a pessoa vê"),
            ("regras", "text", "o combinado antes de jogar"),
            ("anuncios", "announcement", "comunicado oficial da equipe"),
        ]),
        ("comunidade", "conviver entre partidas", [
            ("bate-papo", "text", "conversa geral"),
            ("clipes", "text", "jogada que vale mostrar"),
            ("conquistas", "text", "vitória e marco pessoal"),
        ]),
        ("competitivo", "organizar partida séria", [
            ("lfg", "text", "achar gente para jogar agora"),
            ("resultados", "text", "placar e histórico de partida"),
            ("recrutamento", "text", "entrar no time"),
        ]),
        ("voz", "jogar junto", [
            ("sala geral", "voice", "voz aberta"),
            ("afk", "voice", "quem saiu do teclado"),
        ]),
    ],
    Dominio.GAMING_CASUAL: [
        ("início", "chegar e entender", [
            ("boas-vindas", "text", "primeira coisa que a pessoa vê"),
            ("regras", "text", "o combinado"),
        ]),
        ("comunidade", "conviver", [
            ("bate-papo", "text", "conversa geral"),
            ("clipes", "text", "momento engraçado"),
        ]),
        ("jogo", "falar do jogo", [
            ("dúvidas", "forum", "pergunta de quem está aprendendo"),
            ("sala geral", "voice", "voz aberta"),
        ]),
    ],
    Dominio.RP: [
        ("início", "entrar na cidade", [
            ("boas-vindas", "text", "primeira coisa que a pessoa vê"),
            ("regras", "text", "regra de RP e conduta"),
            ("anuncios", "announcement", "evento e atualização"),
        ]),
        ("personagem", "criar e acompanhar", [
            ("apresente-se", "text", "ficha e história do personagem"),
            ("recrutamento", "text", "entrar em facção"),
        ]),
        ("suporte", "resolver problema", [
            ("dúvidas", "forum", "pergunta sobre a cidade"),
            ("feedback", "forum", "o que melhorar"),
        ]),
        ("voz", "interpretar", [
            ("sala geral", "voice", "voz aberta"),
        ]),
    ],
    Dominio.CLA: [
        ("início", "entrar no clã", [
            ("boas-vindas", "text", "primeira coisa que a pessoa vê"),
            ("regras", "text", "o combinado do clã"),
            ("anuncios", "announcement", "comunicado da liderança"),
        ]),
        ("operação", "organizar o time", [
            ("recrutamento", "text", "entrar no clã"),
            ("lfg", "text", "montar squad agora"),
            ("resultados", "text", "histórico de partida"),
        ]),
        ("voz", "jogar junto", [
            ("sala geral", "voice", "voz aberta"),
            ("afk", "voice", "quem saiu do teclado"),
        ]),
    ],
    Dominio.CRIADOR: [
        ("início", "chegar", [
            ("boas-vindas", "text", "primeira coisa que a pessoa vê"),
            ("regras", "text", "o combinado"),
            ("novidades", "announcement", "vídeo novo e agenda"),
        ]),
        ("comunidade", "conviver", [
            ("bate-papo", "text", "conversa geral"),
            ("feedback", "forum", "o que a pessoa quer ver"),
        ]),
        ("apoio", "resolver", [
            ("dúvidas", "forum", "pergunta sobre conteúdo"),
        ]),
    ],
    Dominio.LOJA: [
        ("início", "entender a loja", [
            ("boas-vindas", "text", "primeira coisa que a pessoa vê"),
            ("regras", "text", "política de compra e troca"),
            ("novidades", "announcement", "produto novo e promoção"),
        ]),
        ("atendimento", "comprar e resolver", [
            ("suporte", "forum", "pedido e problema"),
            ("dúvidas", "forum", "pergunta antes de comprar"),
        ]),
        ("produto", "mostrar o que vende", [
            ("feedback", "forum", "avaliação de quem comprou"),
        ]),
    ],
    Dominio.SAAS: [
        ("início", "entender o produto", [
            ("boas-vindas", "text", "primeira coisa que a pessoa vê"),
            ("novidades", "announcement", "release e changelog"),
        ]),
        ("suporte", "resolver problema", [
            ("dúvidas", "forum", "pergunta de uso"),
            ("feedback", "forum", "pedido de funcionalidade"),
            ("ideias", "forum", "proposta da comunidade"),
        ]),
        ("comunidade", "trocar experiência", [
            ("bate-papo", "text", "conversa entre usuários"),
        ]),
    ],
    Dominio.EDUCACAO: [
        ("início", "começar", [
            ("boas-vindas", "text", "primeira coisa que a pessoa vê"),
            ("regras", "text", "o combinado"),
            ("avisos", "announcement", "aula e prazo"),
        ]),
        ("estudo", "aprender", [
            ("dúvidas", "forum", "pergunta sobre a matéria"),
            ("ideias", "forum", "material e referência"),
        ]),
        ("convivência", "trocar", [
            ("bate-papo", "text", "conversa geral"),
        ]),
    ],
    Dominio.COMUNIDADE: [
        ("início", "chegar e entender", [
            ("boas-vindas", "text", "primeira coisa que a pessoa vê"),
            ("regras", "text", "o combinado"),
            ("anuncios", "announcement", "comunicado da equipe"),
        ]),
        ("comunidade", "conviver", [
            ("bate-papo", "text", "conversa geral"),
            ("apresente-se", "text", "quem chegou agora"),
        ]),
        ("voz", "conversar", [
            ("sala geral", "voice", "voz aberta"),
        ]),
    ],
}

#: Porte grande ganha área extra, específica por domínio. Só adicionar "área de
#: equipe" não bastava: gaming casual grande saía com 8 canais, abaixo da faixa
#: de escalabilidade — ou seja, comunidade grande com estrutura de comunidade
#: pequena. O acréscimo tem que ser conteúdo, não enchimento.
_EXTRA_GRANDE: dict[Dominio, tuple[str, str, list[tuple[str, str, str]]]] = {
    # 'clipes' e 'conquistas' ja estao na base; o extra tem que trazer conteudo
    # novo, nao repetir o que existe.
    Dominio.GAMING_COMPETITIVO: ("extra", "o que não cabe na rotina de partida", [
        ("memes", "text", "piada interna da comunidade"),
        ("análises", "text", "review de partida e estratégia"),
        ("eventos", "text", "torneio e encontro da comunidade"),
    ]),
    # 'clipes' ja existe na base de gaming casual; repetir aqui era duplicata,
    # que e o defeito que o QA de design aponta.
    Dominio.GAMING_CASUAL: ("mídia", "mostrar o que a comunidade faz", [
        ("construções", "text", "o que o pessoal fez no jogo"),
        ("memes", "text", "piada interna da comunidade"),
        ("eventos", "text", "o que a comunidade organiza"),
    ]),
    Dominio.RP: ("mídia", "registrar a história da cidade", [
        ("clipes", "text", "cena que vale guardar"),
        ("histórias", "text", "arco e acontecimento do RP"),
    ]),
    Dominio.CLA: ("mídia", "registrar o histórico do clã", [
        ("clipes", "text", "jogada que vale mostrar"),
        ("conquistas", "text", "vitória do clã"),
    ]),
    Dominio.CRIADOR: ("mídia", "conteúdo da comunidade", [
        ("clipes", "text", "corte e momento do canal"),
        ("fanart", "text", "o que a comunidade criou"),
    ]),
    Dominio.LOJA: ("comunidade", "quem já comprou", [
        ("avaliações", "text", "o que achou do produto"),
        ("trocas", "text", "pós-venda entre clientes"),
    ]),
    Dominio.SAAS: ("integrações", "uso avançado", [
        ("api", "text", "dúvida técnica de integração"),
        ("casos de uso", "text", "como o pessoal usa na prática"),
    ]),
    Dominio.EDUCACAO: ("turmas", "organizar por grupo", [
        ("materiais", "text", "apostila e referência da turma"),
        ("trabalhos", "text", "entrega e discussão"),
    ]),
    Dominio.COMUNIDADE: ("mídia", "compartilhar", [
        ("mídia", "text", "imagem e vídeo do pessoal"),
        ("memes", "text", "piada interna da comunidade"),
    ]),
}

#: O que o porte corta. Ordem de corte: o último de cada lista some primeiro.
_CORTE_POR_PORTE: dict[Porte, int] = {
    Porte.PEQUENO: 2,   # corta até 2 canais por categoria
    Porte.MEDIO: 0,
    Porte.GRANDE: -1,   # negativo = acrescenta área extra
}

#: Hierarquia de cargos por porte (spec 41: só quando faz sentido).
_HIERARQUIA: dict[Porte, list[tuple[str, int]]] = {
    # (nome, posição relativa — maior = mais alto)
    Porte.PEQUENO: [("dono", 40), ("mod", 30), ("membro", 10)],
    Porte.MEDIO: [("dono", 50), ("admin", 40), ("mod", 30), ("membro", 10)],
    Porte.GRANDE: [("dono", 60), ("admin", 50), ("gerente", 40),
                   ("mod", 30), ("ajudante", 20), ("membro", 10)],
}

#: Cargos de identidade por domínio (spec 40: cor/interesse, sem permissão).
_IDENTIDADE: dict[Dominio, list[str]] = {
    Dominio.GAMING_COMPETITIVO: ["pro player", "streamer", "torcida"],
    Dominio.GAMING_CASUAL: ["veterano", "novato"],
    Dominio.RP: ["facção", "civil", "staff rp"],
    Dominio.CLA: ["titular", "reserva"],
    Dominio.CRIADOR: ["inscrito", "apoiador"],
    Dominio.LOJA: ["cliente", "vip"],
    Dominio.SAAS: ["usuário", "beta tester"],
    Dominio.EDUCACAO: ["aluno", "monitor"],
    Dominio.COMUNIDADE: ["ativo", "novato"],
}

#: Onboarding por domínio (spec 43): a jornada, não uma lista de canal.
_ONBOARDING: dict[Dominio, list[str]] = {
    Dominio.GAMING_COMPETITIVO: [
        "ler as regras", "se apresentar", "pegar o cargo de plataforma",
        "procurar partida no lfg",
    ],
    Dominio.RP: [
        "ler as regras de rp", "criar a ficha do personagem",
        "pedir entrada em facção", "entrar na primeira cena",
    ],
    Dominio.LOJA: [
        "ler a política de compra", "ver as novidades", "chamar no suporte",
    ],
    # 'ler as regras' nao e opcional: a spec 43 poe ACEITAR REGRAS na jornada de
    # qualquer comunidade, e comunidade de produto tambem tem combinado de
    # conduta. Estava pulando esse passo.
    Dominio.SAAS: [
        "ler as regras", "ver o changelog", "tirar dúvida no suporte", "propor ideia",
    ],
    Dominio.EDUCACAO: [
        "ler os avisos", "tirar dúvida", "participar da conversa",
    ],
    Dominio.CLA: [
        "ler as regras", "se candidatar no recrutamento", "entrar no squad",
    ],
    Dominio.CRIADOR: [
        "ler as regras", "ver as novidades", "dar feedback",
    ],
    Dominio.GAMING_CASUAL: [
        "ler as regras", "se apresentar", "entrar na sala de voz",
    ],
    Dominio.COMUNIDADE: [
        "ler as regras", "se apresentar", "entrar na conversa",
    ],
}


#: Vocabulário de tema (spec 34, 80, 81, 82). O tema influencia a ESTRUTURA, não
#: só emoji — que é o que a spec 34 diz explicitamente ("não limitar tema a
#: emojis").
#:
#: POR QUE ISTO NÃO É O "TEMPLATE FORTNITE FIXO" QUE A SPEC 78 PROÍBE
#: ------------------------------------------------------------------
#: O template proibido é: tema → servidor inteiro pronto. Aqui o tema acrescenta
#: no máximo _MAX_CANAIS_DE_TEMA canais, e só quando o porte comporta. A
#: estrutura continua vindo de domínio × porte × público × estilo. "Fortnite
#: competitivo" e "Fortnite casual" seguem diferentes; o tema só ajusta o
#: vocabulário de dentro.
#:
#: E spec 80 manda "não criar tudo obrigatoriamente" — por isso o teto.
_TEMA_CANAIS: dict[str, list[tuple[str, str, str]]] = {
    "fortnite": [
        ("zero build", "text", "partida sem construção"),
        ("creative", "text", "mapa e ilha criada pela comunidade"),
        ("torneios", "text", "campeonato e inscrição"),
    ],
    "minecraft": [
        ("survival", "text", "mundo e progresso do survival"),
        ("construções", "text", "o que o pessoal construiu"),
        ("mods", "text", "modpack e configuração"),
    ],
    "gta rp": [
        ("facções", "text", "organização e território"),
        ("economia", "text", "trabalho e dinheiro da cidade"),
        ("eventos", "text", "cena e acontecimento do RP"),
    ],
    "valorant": [
        ("agentes", "text", "composição e estratégia"),
        ("torneios", "text", "campeonato e inscrição"),
    ],
    "anime": [
        ("recomendações", "text", "o que assistir"),
        ("fanart", "text", "arte da comunidade"),
    ],
}

#: Teto de canais acrescentados por tema. Spec 80: "não criar tudo
#: obrigatoriamente". Três já é o máximo que não vira enchimento.
_MAX_CANAIS_DE_TEMA = 2


def canais_do_tema(tema: str, porte: "Porte") -> list[tuple[str, str, str]]:
    """Canais que o tema acrescenta, ou lista vazia.

    Porte pequeno não recebe: comunidade de 20 pessoas com canal de torneio é
    canal morto, que é o defeito que a spec 44 manda evitar.
    """
    if porte == Porte.PEQUENO:
        return []
    baixo = (tema or "").lower()
    for chave, canais in _TEMA_CANAIS.items():
        if chave in baixo:
            return canais[:_MAX_CANAIS_DE_TEMA]
    return []


def _norm_nome(nome: str) -> str:
    """Normaliza para comparar. Igual ao de design_check, mas local: importar de
    lá criaria dependência circular (design_check importa daqui)."""
    s = (nome or "").strip().lower()
    for sep in ("・", "「", "」", "·", "•", "|", "-", "—", "_"):
        s = s.replace(sep, " ")
    s = "".join(ch for ch in s if ch.isalnum() or ch == " ").strip()
    return " ".join(s.split())


def projetar(briefing: Briefing) -> Arquitetura:
    """Compõe a arquitetura. Determinístico: mesmo briefing, mesmo resultado."""
    base = _BASE[briefing.dominio]
    corte = _CORTE_POR_PORTE[briefing.porte]

    categorias: list[ProjetoCategoria] = []
    for nome_cat, proposito_cat, canais in base:
        lista = list(canais)
        if corte > 0:
            # Porte pequeno: mantém os canais essenciais (os primeiros de cada
            # área) e corta o resto. Nunca corta tudo de uma categoria, senão a
            # categoria nasce vazia — que é exatamente o defeito que o QA da
            # Fase 5 passou a apontar.
            lista = lista[: max(1, len(lista) - corte)]
        projeto = ProjetoCategoria(
            nome=_n(briefing, nome_cat),
            proposito=proposito_cat,
            canais=[
                ProjetoCanal(nome=_n(briefing, nome_canal), tipo=tipo, proposito=prop)
                for nome_canal, tipo, prop in lista
            ],
        )
        categorias.append(projeto)

    # Porte grande ganha área de bastidor (spec 44: mais granularidade)
    if corte < 0:
        categorias.append(ProjetoCategoria(
            nome=_n(briefing, "equipe"),
            proposito="onde a staff organiza sem aparecer para todo mundo",
            canais=[
                ProjetoCanal(nome=_n(briefing, "log"), tipo="text",
                             proposito="registro do que a equipe fez", privado=True),
                ProjetoCanal(nome=_n(briefing, "equipe"), tipo="text",
                             proposito="conversa da staff", privado=True),
            ],
        ))
        # E área de conteúdo extra. Só a área de staff deixava comunidade grande
        # com estrutura de comunidade pequena (medido: gaming casual grande saía
        # com 8 canais, fora da faixa de escalabilidade).
        nome_extra, prop_extra, canais_extra = _EXTRA_GRANDE[briefing.dominio]
        categorias.append(ProjetoCategoria(
            nome=_n(briefing, nome_extra),
            proposito=prop_extra,
            canais=[
                ProjetoCanal(nome=_n(briefing, nome), tipo=tipo, proposito=prop)
                for nome, tipo, prop in canais_extra
            ],
        ))

    # Tema influencia a estrutura (spec 34). Entra na última categoria de
    # conteúdo — não cria categoria nova, senão o tema viraria área própria e o
    # servidor pequeno ganharia categoria quase vazia.
    extras = canais_do_tema(briefing.tema, briefing.porte)
    if extras and categorias:
        alvo = max(
            (c for c in categorias if not any(x.privado for x in c.canais)),
            key=lambda c: len(c.canais),
            default=None,
        )
        if alvo is not None:
            existentes = {_norm_nome(c.nome) for c in alvo.canais}
            for nome, tipo, proposito in extras:
                decorado = _n(briefing, nome)
                if _norm_nome(decorado) in existentes:
                    continue  # não duplica o que a base já tem
                alvo.canais.append(
                    ProjetoCanal(nome=decorado, tipo=tipo, proposito=proposito)
                )

    cargos = _cargos(briefing)
    return Arquitetura(
        briefing=briefing,
        categorias=categorias,
        cargos=cargos,
        onboarding=list(_ONBOARDING[briefing.dominio]),
    )


def _cargos(briefing: Briefing) -> list[ProjetoCargo]:
    """Funcionais + identidade, separados (spec 40).

    Nenhum funcional nasce com ADMINISTRATOR: menor privilégio (spec 42) e a
    Fase 5 já recusa em código cargo novo com permissão administrativa.
    """
    saida: list[ProjetoCargo] = []
    for nome, posicao in _HIERARQUIA[briefing.porte]:
        permissoes: list[str] = []
        if nome in ("admin",):
            permissoes = ["manage_channels", "manage_roles", "kick_members"]
        elif nome in ("mod", "gerente"):
            permissoes = ["manage_messages", "manage_channels"]
        elif nome == "ajudante":
            permissoes = ["manage_messages"]
        saida.append(ProjetoCargo(
            nome=nome, tipo="funcional", posicao=posicao, permissoes=permissoes,
        ))
    for i, nome in enumerate(_IDENTIDADE[briefing.dominio]):
        saida.append(ProjetoCargo(
            nome=nome, tipo="identidade", posicao=5 - i,
            cor=0x3498DB, permissoes=[],
        ))
    return saida


# ------------------------------------------------------------------ score (136)
def design_score(arq: Arquitetura) -> dict[str, object]:
    """Avaliação interna (spec 136). Não é verdade absoluta e não vai para o
    usuário como nota — serve para decidir refazer antes de executar (spec 137).

    Cada critério devolve (pontos 0-10, motivo). O motivo é o que importa: score
    sem explicação é número decorativo.
    """
    criterios: dict[str, tuple[int, str]] = {}

    # coerência: nomenclatura uniforme
    nomes = arq.nomes_de_canal()
    estilos = {("emoji" if any(ch in n for ch in "・「」") or
                any(e in n for e in _EMOJI.values()) else "limpo") for n in nomes}
    criterios["coerencia"] = (10 if len(estilos) <= 1 else 3,
                              "nomenclatura uniforme" if len(estilos) <= 1
                              else "misturou estilo de nome")

    # navegação: nenhuma categoria vazia, nenhuma gigante
    vazias = [c.nome for c in arq.categorias if not c.canais]
    gigantes = [c.nome for c in arq.categorias if len(c.canais) > 12]
    pontos = 10
    motivos = []
    if vazias:
        pontos -= 4
        motivos.append(f"{len(vazias)} categoria vazia")
    if gigantes:
        pontos -= 3
        motivos.append(f"{len(gigantes)} categoria com mais de 12 canais")
    criterios["navegacao"] = (max(0, pontos), "; ".join(motivos) or "áreas bem divididas")

    # clareza: todo canal tem propósito (spec 38)
    sem_funcao = [c.nome for cat in arq.categorias for c in cat.canais if not c.tem_funcao()]
    criterios["clareza"] = (10 if not sem_funcao else 2,
                            "todo canal tem função" if not sem_funcao
                            else f"{len(sem_funcao)} canal sem função declarada")

    # redundância: nome repetido
    duplicados = len(nomes) - len({n.lower() for n in nomes})
    criterios["redundancia"] = (10 if duplicados == 0 else 0,
                                "sem canal duplicado" if duplicados == 0
                                else f"{duplicados} canal com nome repetido")

    # cargos: funcionais e identidade separados, sem admin desnecessário
    funcionais = [c for c in arq.cargos if c.tipo == "funcional"]
    identidade = [c for c in arq.cargos if c.tipo == "identidade"]
    com_admin = [c.nome for c in funcionais if "administrator" in c.permissoes]
    pontos = 10
    motivos = []
    if not identidade:
        pontos -= 3
        motivos.append("nenhum cargo de identidade")
    if com_admin:
        pontos -= 5
        motivos.append(f"{len(com_admin)} cargo funcional com administrator")
    criterios["cargos"] = (max(0, pontos), "; ".join(motivos) or "hierarquia e identidade separadas")

    # onboarding: jornada existe (spec 43)
    criterios["onboarding"] = (10 if arq.onboarding else 0,
                               "jornada definida" if arq.onboarding
                               else "sem jornada de entrada")

    # escalabilidade: porte coerente com o tamanho (spec 44)
    total = arq.total_canais
    esperado = {Porte.PEQUENO: (4, 12), Porte.MEDIO: (6, 22), Porte.GRANDE: (10, 40)}[arq.briefing.porte]
    ok = esperado[0] <= total <= esperado[1]
    criterios["escalabilidade"] = (
        10 if ok else 2,
        f"{total} canais para porte {arq.briefing.porte.value}"
        + ("" if ok else f", fora da faixa {esperado[0]}-{esperado[1]}"),
    )

    geral = round(sum(p for p, _ in criterios.values()) / len(criterios), 1)
    return {"geral": geral, "criterios": criterios}


def precisa_refazer(arq: Arquitetura, minimo: float = 8.0) -> bool:
    """Spec 137: se parecer genérico ou ruim, refazer antes de executar.

    Limiar em 8.0 e nao mais baixo de proposito: com 6.0 uma arquitetura com um
    canal sem funcao e um nome duplicado passava, e esses sao exatamente os dois
    defeitos que a Fase 5 mediu no modelo real. Nota 7 ainda e projeto ruim.
    """
    return float(design_score(arq)["geral"]) < minimo  # type: ignore[arg-type]
