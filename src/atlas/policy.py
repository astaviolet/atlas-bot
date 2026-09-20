"""Politica de seguranca. Camada dura, independente do que o modelo pedir.

Hierarquia efetiva:
    REGRAS DO SISTEMA -> POLITICAS DO EXECUTOR -> REGRAS DE SEGURANCA
    -> CONTEXTO DO GUILD -> PEDIDO DO USUARIO

O modelo so escolhe *dentro* do que este modulo permite.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from .errors import (
    ForbiddenAction,
    GuildIsolationViolation,
    PromptInjectionBlocked,
    QuotaExceeded,
)
from .models import NEVER_GRANTABLE, Perm

# ---------------------------------------------------------------------------
# Ferramentas que NAO EXISTEM. Nao basta nao registrar: o executor recusa
# explicitamente se algum dia alguem tentar re-registrar.
# ---------------------------------------------------------------------------
FORBIDDEN_CAPABILITIES: frozenset[str] = frozenset(
    {
        # moderacao de pessoas
        "ban_member", "banir", "kick_member", "expulsar",
        "timeout_member", "untimeout_member", "set_timeout", "remover_timeout",
        "add_role_to_member", "remove_role_from_member",
        "add_member_role", "remove_member_role",
        "set_nickname", "change_nickname", "mudar_nickname",
        "move_voice_member", "disconnect_member",
        "set_member_permissions", "edit_member_permissions",
        # comunicacao
        "send_dm", "dm_member", "direct_message", "mandar_dm",
        "mass_message", "broadcast", "send_bulk", "spam", "flood",
        "mention_everyone", "mention_here", "ping_everyone",
        # isolamento
        "set_guild", "switch_guild", "use_guild", "list_guilds",
        "act_on_other_guild", "for_each_guild",
        # dados de membros
        "list_members", "get_members", "get_member", "fetch_members",
        "search_members", "export_members", "member_data",
        # escape
        "raw_api_call", "http_request", "exec", "eval", "shell",
        "run_code", "arbitrary_request",
    }
)

# Ferramentas que o agente tem. Tudo fora daqui e recusado.
ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        # leitura
        "get_server_info",
        "get_channels",
        "get_categories",
        "get_channel",
        "get_roles",
        "get_role",
        # canais
        "create_channel",
        "edit_channel",
        "delete_channel",
        "create_category",
        "edit_category",
        "delete_category",
        "move_channel",
        "set_channel_permissions",
        "reorder_channels",
        # cargos
        "create_role",
        "edit_role",
        "delete_role",
        "move_role",
        "set_role_permissions",
        # servidor
        "edit_server",
    }
)

# Acoes que removem coisa. Precisam de confirmacao acima do limiar.
DESTRUCTIVE_TOOLS: frozenset[str] = frozenset(
    {"delete_channel", "delete_category", "delete_role"}
)

# Ferramentas que apenas leem o estado. Tudo que NAO esta aqui muda o servidor,
# entao a lista e explicita em vez de depender do prefixo "get_": se alguem
# criar uma ferramenta nova, ela nasce considerada mutacao (lado seguro).
READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "get_server_info",
        "get_channels",
        "get_categories",
        "get_channel",
        "get_roles",
        "get_role",
    }
)


def is_read_only(tool: str) -> bool:
    """True quando a ferramenta nao altera o servidor."""
    return tool in READ_ONLY_TOOLS

# Acoes que mudam o servidor inteiro.
SERVER_WIDE_TOOLS: frozenset[str] = frozenset({"edit_server"})


@dataclass(frozen=True)
class ActionBudget:
    """Quanto um unico plano pode gastar."""

    max_actions: int
    max_creates: int
    max_deletes: int

    def check(self, actions: int, creates: int, deletes: int) -> None:
        if actions > self.max_actions:
            raise QuotaExceeded(
                f"plano com {actions} acoes, maximo {self.max_actions}",
                user_message=(
                    f"Esse pedido viraria {actions} operacoes. Meu teto por solicitacao e "
                    f"{self.max_actions}. Peça em blocos menores, por categoria."
                ),
            )
        if creates > self.max_creates:
            raise QuotaExceeded(
                f"plano com {creates} criacoes, maximo {self.max_creates}",
                user_message=(
                    f"Voce pediu {creates} criacoes de uma vez e meu limite e {self.max_creates}. "
                    f"Vamos fazer por partes?"
                ),
            )
        if deletes > self.max_deletes:
            raise QuotaExceeded(
                f"plano com {deletes} exclusoes, maximo {self.max_deletes}",
                user_message=(
                    f"{deletes} exclusoes de uma vez passa do meu limite ({self.max_deletes}). "
                    f"Me diga exatamente o que sai e eu faco em etapas."
                ),
            )


# Padroes de prompt injection. Sao *sinal*, nao a unica defesa: a defesa real
# e que nada disso muda o comportamento do executor.
_INJECTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # "ignore todas as instrucoes" / "ignore all previous instructions"
    (re.compile(
        r"\b(ignore|esque[çc]a|desconsider[ea]|descart[ea])\s+(todas\s+as\s+|todos\s+os\s+|all\s+|the\s+)"
        r"(instru[çc][õo]es?|regras?|prompts?)", re.I),
     "pedido para ignorar todas as instrucoes"),
    # ordem inversa: "instrucoes anteriores" / "regras do sistema"
    (re.compile(
        r"\b(ignore|esque[çc]a|desconsider[ea]|descart[ea]|disregard)\b.{0,30}"
        r"\b(instru[çc][õo]es?|regras?|prompts?)\s+(anteriores?|pr[ée]vias?|previous|above|do\s+sistema)", re.I),
     "pedido para ignorar instrucoes anteriores"),
    (re.compile(r"\bignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|rules?)", re.I),
     "pedido para ignorar instrucoes anteriores"),
    # troca de papel / modo sem restricao
    (re.compile(
        r"\bvoc[êe]\s+(agora\s+)?(é|e|está|esta|virou|passou\s+a\s+ser)\s+(um\s+|o\s+|uma\s+)?"
        r"(developer|dev|admin|deus|god|dan|jailbroken|modo\s+(desenvolvedor|admin))", re.I),
     "tentativa de trocar o papel do agente"),
    (re.compile(r"\b(developer\s+mode|modo\s+desenvolvedor|jailbreak|sem\s+(nenhuma\s+)?(restri[çc][ãa]o|limita[çc][ãa]o|filtro))\b", re.I),
     "pedido de modo sem restricoes"),
    # liberacao de moderacao
    (re.compile(
        r"\b(voc[êe]\s+)?(agora\s+)?(pode|tem\s+permiss[ãa]o\s+(para|de)|est[aá]\s+liberado\s+(para|pra))\s+"
        r"(banir|expulsar|kickar|dar\s+timeout|moderar)", re.I),
     "tentativa de liberar moderacao"),
    # exfiltracao do prompt
    (re.compile(
        r"\b(revela|mostre?|imprima|exiba|printe?|me\s+d[aê])\b.{0,40}"
        r"\b(system\s+prompt|prompt\s+de\s+sistema|instru[çc][õo]es?\s+do\s+sistema|suas?\s+instru[çc][õo]es)\b", re.I),
     "pedido do prompt de sistema"),
    # quebra do isolamento de servidor
    (re.compile(
        r"\b(ignore|esque[çc]a|remove|tira|quebre?)\b.{0,30}"
        r"\b(restri[çc][ãa]o|limita[çc][ãa]o|isolamento)\b.{0,25}\bservidor\b", re.I),
     "tentativa de remover o isolamento de servidor"),
    # injecao de novas regras
    (re.compile(r"\b(new\s+instructions?|novas?\s+instru[çc][õo]es|a\s+partir\s+de\s+agora\s+voc[êe])\b", re.I),
     "tentativa de injetar novas instrucoes"),
)


def detect_injection(text: str) -> list[str]:
    """Devolve os motivos detectados. Vazio = nada suspeito."""
    hits: list[str] = []
    for pattern, reason in _INJECTION_PATTERNS:
        if pattern.search(text):
            hits.append(reason)
    return hits


def has_invisible_or_weird_unicode(text: str) -> list[str]:
    """Detecta caractere invisivel / bidi override, tecnica comum de evasao."""
    problems: list[str] = []
    for ch in text:
        if ch in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"):
            problems.append(f"zero-width U+{ord(ch):04X}")
        elif "\u202a" <= ch <= "\u202e" or "\u2066" <= ch <= "\u2069":
            problems.append(f"bidi-override U+{ord(ch):04X}")
        elif unicodedata.category(ch) == "Cf":
            problems.append(f"format-char U+{ord(ch):04X}")
    # sem duplicata, preservando ordem
    seen: set[str] = set()
    return [p for p in problems if not (p in seen or seen.add(p))]


class Policy:
    """Ponto unico de decisao de seguranca."""

    def __init__(
        self,
        *,
        guild_id: int,
        budget: ActionBudget,
        destructive_confirm_threshold: int = 3,
    ) -> None:
        self.guild_id = int(guild_id)
        self.budget = budget
        self.destructive_confirm_threshold = destructive_confirm_threshold

    # -- ferramentas --------------------------------------------------------
    def check_tool(self, name: str) -> None:
        normalized = str(name).strip().lower()
        if normalized in FORBIDDEN_CAPABILITIES:
            raise ForbiddenAction(
                f"ferramenta proibida solicitada: {normalized}",
                user_message=f"Eu nao tenho a capacidade **{normalized}**, e nao vou ter. Este agente so configura a estrutura do servidor.",
            )
        if normalized not in ALLOWED_TOOLS:
            raise ForbiddenAction(
                f"ferramenta fora da lista permitida: {normalized}",
                user_message=f"**{normalized}** nao e uma ferramenta disponivel para mim.",
            )

    # -- isolamento ---------------------------------------------------------
    def bind_guild(self, requested: Any) -> int:
        """Retorna SEMPRE o guild do contexto. Recusa qualquer outro."""
        if requested is None:
            return self.guild_id
        try:
            value = int(requested)
        except (TypeError, ValueError) as exc:
            raise GuildIsolationViolation(f"guild_id invalido: {requested!r}") from exc
        if value != self.guild_id:
            raise GuildIsolationViolation(
                f"modelo pediu guild {value}, contexto e {self.guild_id}",
                user_message=(
                    "So posso agir no servidor onde esta conversa esta acontecendo. "
                    "Para configurar outro servidor, fale comigo la dentro."
                ),
            )
        return self.guild_id

    def strip_foreign_guild_keys(self, params: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Remove chaves de guild que o modelo possa ter contrabandeado.

        Retorna os parametros limpos e as chaves removidas (para auditoria).
        """
        cleaned: dict[str, Any] = {}
        removed: list[str] = []
        foreign = {"guild_id", "guild", "server_id", "server", "guild_ids", "target_guild"}
        for key, value in params.items():
            if str(key).strip().lower() in foreign:
                removed.append(key)
                continue
            cleaned[key] = value
        return cleaned, removed

    # -- texto do usuario ---------------------------------------------------
    def screen_user_text(self, text: str) -> dict[str, Any]:
        """Analisa o texto. NAO altera o que sera processado, so registra/alerta."""
        return {
            "injection_hits": detect_injection(text),
            "unicode_issues": has_invisible_or_weird_unicode(text),
        }

    def guard_against_injection(self, text: str) -> list[str]:
        """Levanta excecao apenas para as tentativas explicitas de tomada de controle.

        Nota: isso e defesa em profundidade. Mesmo sem levantar, o executor ja
        ignora pedidos de mudar as proprias regras.
        """
        hits = detect_injection(text)
        if hits:
            raise PromptInjectionBlocked(
                "; ".join(hits),
                user_message=(
                    "Mensagens na conversa nao mudam minhas regras. "
                    "Continuo sem moderar pessoas e sem sair deste servidor. "
                    "Se quiser, me diga o que voce quer configurar que eu faco."
                ),
            )
        return hits

    # -- cotas --------------------------------------------------------------
    def check_budget(self, *, actions: int, creates: int, deletes: int) -> None:
        self.budget.check(actions, creates, deletes)

    def needs_confirmation(self, tool: str, destructive_count: int) -> bool:
        if tool in DESTRUCTIVE_TOOLS:
            return destructive_count >= self.destructive_confirm_threshold
        return False

    # -- permissao nunca concedivel ----------------------------------------
    @staticmethod
    def never_grantable_names() -> list[str]:
        return sorted(p.name.lower() for p in NEVER_GRANTABLE)

    _ = Perm  # mantem a referencia explicita para leitura do modulo
