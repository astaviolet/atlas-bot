"""Registro de ferramentas e contexto de execucao.

Nenhuma ferramenta recebe `guild_id` como parametro. O servidor vem do contexto,
que por sua vez vem da interacao real do Discord.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..config import Limits
from ..errors import ForbiddenAction
from ..gateway import GuildGateway
from ..models import GuildSnapshot, Perm
from ..policy import Policy


@dataclass
class ToolContext:
    """Tudo que uma ferramenta pode enxergar. Nao ha caminho para outro guild."""

    guild_id: int
    gateway: GuildGateway
    policy: Policy
    limits: Limits
    snapshot: GuildSnapshot
    confirmations: set[str] = field(default_factory=set)
    #: Canal de onde veio a mensagem do usuario. Vem do contexto real da
    #: interacao do Discord, nunca de parametro do modelo. Sem isso o agente
    #: nao tem como resolver "este canal", "aqui", "esse" - e fica pedindo o id
    #: de volta ou, pior, chutando um canal errado.
    source_channel_id: int | None = None
    #: Quem pediu. Tambem vem do contexto real do Discord. E CONTEXTO, nao
    #: autorizacao: saber o id de quem falou ajuda a resolver "me da acesso",
    #: mas a checagem de permissao continua acontecendo no codigo.
    source_author_id: int | None = None
    source_author_name: str | None = None

    def refresh(self) -> GuildSnapshot:
        self.snapshot = self.gateway.snapshot()
        return self.snapshot


ToolHandler = Callable[[ToolContext, dict[str, Any]], Any]
Verifier = Callable[[ToolContext, dict[str, Any], Any], bool]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    destructive: bool = False
    destructive_count: Callable[[dict[str, Any]], int] | None = None
    requires: Perm | None = None
    verify: Verifier | None = None
    # usado para montar o rotulo legivel no embed de resultado
    label: Callable[[dict[str, Any]], str] | None = None

    def count_destructive(self, params: dict[str, Any]) -> int:
        if not self.destructive:
            return 0
        if self.destructive_count is not None:
            return int(self.destructive_count(params))
        return 1

    def describe(self, params: dict[str, Any]) -> str:
        if self.label is not None:
            try:
                return self.label(params)
            except Exception:  # noqa: BLE001 - rotulo nunca derruba a execucao
                pass
        return self.name

    def to_declaration(self) -> dict[str, Any]:
        """Declaracao em JSON Schema padrao (portatil entre provedores).

        A conversao para o envelope especifico de cada API fica em
        `atlas.ai.schema`, nao aqui. As ferramentas nao sabem quem as consome.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """Lista fechada. Registrar algo proibido levanta na hora."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        normalized = tool.name.strip().lower()
        if normalized != tool.name:
            raise ValueError(f"nome de ferramenta deve ser lowercase: {tool.name!r}")
        try:
            # delega a decisao de seguranca a um unico lugar
            Policy(guild_id=0, budget=None).check_tool(normalized)  # type: ignore[arg-type]
        except ForbiddenAction:
            raise
        if normalized in self._tools:
            raise ValueError(f"ferramenta duplicada: {normalized}")
        self._tools[normalized] = tool

    def register_all(self, tools: Iterable[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> Tool:
        key = str(name).strip().lower()
        tool = self._tools.get(key)
        if tool is None:
            raise ForbiddenAction(
                f"ferramenta inexistente: {key}",
                user_message=f"Eu nao tenho uma ferramenta chamada **{key}**.",
            )
        return tool

    def has(self, name: str) -> bool:
        return str(name).strip().lower() in self._tools

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def declarations(self) -> list[dict[str, Any]]:
        return [tool.to_declaration() for tool in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)
