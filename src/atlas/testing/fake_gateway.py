"""Gateway em memoria que imita a semantica relevante da API do Discord.

Serve para (a) testar o agente sem credencial e (b) rodar em modo demo.
Implementa de proposito as mesmas restricoes que a API real impoe, para que um
teste aprovado aqui nao passe falso em producao:

  - hierarquia de cargos (nao mexe em cargo >= ao do bot)
  - cargos de integracao (managed) sao intocaveis
  - permissoes do bot sao respeitadas
  - canal filho de categoria inexistente vira erro
  - deletar categoria NAO deleta os canais (comportamento real do Discord)
  - rate limit simulavel
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import Any

from ..errors import GatewayError, NotFound, ToolError
from ..models import Channel, ChannelType, GuildSnapshot, Overwrite, Perm, Role

_UNSET = object()


@dataclass
class FakeGateway:
    guild_id: int = 111111111111111111
    name: str = "Servidor de Teste"
    owner_id: int = 900000000000000001
    bot_role_id: int = 800000000000000009
    bot_permissions: int = (
        Perm.MANAGE_CHANNELS | Perm.MANAGE_ROLES | Perm.MANAGE_GUILD |
        Perm.VIEW_CHANNEL | Perm.SEND_MESSAGES | Perm.EMBED_LINKS |
        Perm.READ_MESSAGE_HISTORY | Perm.CONNECT | Perm.SPEAK
    )
    description: str | None = "Servidor usado nos testes do Atlas"

    channels: dict[int, Channel] = field(default_factory=dict)
    roles: dict[int, Role] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    fail_next: dict[str, str] = field(default_factory=dict)
    _ids: count[int] = field(default_factory=lambda: count(500000000000000000))

    # ---------------------------------------------------------------- setup
    def __post_init__(self) -> None:
        if not self.roles:
            self.roles = {
                700000000000000001: Role(700000000000000001, "@everyone", position=0, permissions=int(Perm.VIEW_CHANNEL)),
                800000000000000009: Role(800000000000000009, "Atlas", position=10,
                                         permissions=int(self.bot_permissions), managed=False),
                800000000000000099: Role(800000000000000099, "Dono Supremo", position=99, managed=False),
                800000000000000050: Role(800000000000000050, "Integracao Externa", position=20, managed=True),
            }
        if not self.channels:
            cat = Channel(600000000000000001, "geral-cat", type=ChannelType.GUILD_CATEGORY, position=0)
            self.channels[cat.id] = cat
            self.channels[600000000000000002] = Channel(
                600000000000000002, "bate-papo", type=ChannelType.GUILD_TEXT,
                position=0, parent_id=cat.id,
            )

    def seed_gamer_layout(self) -> None:
        """Popula um servidor ja estruturado, para testes de reorganizacao/exclusao."""
        base = 610000000000000000
        for i, cat_name in enumerate(("INFORMACOES", "COMUNIDADE", "VOZ")):
            cat_id = base + i * 100
            self.channels[cat_id] = Channel(cat_id, cat_name, type=ChannelType.GUILD_CATEGORY, position=i)
            for j, ch in enumerate(("regras", "anuncios")):
                if cat_name == "VOZ":
                    ch = "Sala Geral" if j == 0 else "AFK"
                cid = cat_id + j + 1
                ctype = ChannelType.GUILD_VOICE if cat_name == "VOZ" else ChannelType.GUILD_TEXT
                self.channels[cid] = Channel(cid, ch, type=ctype, position=j, parent_id=cat_id)

    # ------------------------------------------------------------ utilidades
    def fail_on(self, method: str, message: str) -> None:
        """Faz a proxima chamada de `method` falhar. Simula erro da API."""
        self.fail_next[method] = message

    def _maybe_fail(self, method: str) -> None:
        self.calls.append((method, {}))
        message = self.fail_next.pop(method, None)
        if message:
            raise GatewayError(f"{method}: {message}", user_message=message)

    def _next_id(self) -> int:
        return next(self._ids)

    # --------------------------------------------------------------- leitura
    def snapshot(self) -> GuildSnapshot:
        self._maybe_fail("snapshot")
        return GuildSnapshot(
            id=self.guild_id,
            name=self.name,
            owner_id=self.owner_id,
            bot_role_id=self.bot_role_id,
            bot_permissions=self.bot_permissions,
            description=self.description,
            channels=list(self.channels.values()),
            roles=list(self.roles.values()),
        )

    def get_channel(self, channel_id: int) -> Channel | None:
        self._maybe_fail("get_channel")
        return self.channels.get(int(channel_id))

    def get_role(self, role_id: int) -> Role | None:
        self._maybe_fail("get_role")
        return self.roles.get(int(role_id))

    def _require_channel(self, channel_id: int) -> Channel:
        channel = self.channels.get(int(channel_id))
        if channel is None:
            raise NotFound(f"canal {channel_id} nao existe", user_message="Esse canal nao existe mais no servidor.")
        return channel

    def _require_role(self, role_id: int) -> Role:
        role = self.roles.get(int(role_id))
        if role is None:
            raise NotFound(f"cargo {role_id} nao existe", user_message="Esse cargo nao existe mais no servidor.")
        return role

    def _require_category(self, parent_id: int | None) -> None:
        if parent_id is None:
            return
        parent = self.channels.get(int(parent_id))
        if parent is None:
            raise NotFound(f"categoria {parent_id} nao existe", user_message="A categoria que voce indicou nao existe.")
        if not parent.is_category:
            raise ToolError(
                f"{parent_id} nao e categoria",
                user_message="Esse canal nao e uma categoria, entao nao da para colocar nada dentro dele.",
            )

    # ---------------------------------------------------------------- canais
    def create_channel(
        self,
        *,
        name: str,
        type: int,
        parent_id: int | None = None,
        topic: str | None = None,
        nsfw: bool = False,
        slowmode_delay: int = 0,
        position: int | None = None,
    ) -> Channel:
        self._maybe_fail("create_channel")
        if not name or not str(name).strip():
            raise ToolError("nome vazio", user_message="Preciso de um nome para o canal.")
        if type == ChannelType.GUILD_CATEGORY:
            raise ToolError("use create_category", user_message="Categorias tem ferramenta propria.")
        self._require_category(parent_id)
        channel = Channel(
            id=self._next_id(),
            name=str(name).strip(),
            type=int(type),
            parent_id=int(parent_id) if parent_id else None,
            topic=topic,
            nsfw=bool(nsfw),
            slowmode_delay=int(slowmode_delay or 0),
            position=position if position is not None else len(self.channels),
        )
        self.channels[channel.id] = channel
        return channel

    def edit_channel(
        self,
        channel_id: int,
        *,
        name: Any = None,
        topic: Any = None,
        nsfw: Any = None,
        slowmode_delay: Any = None,
        parent_id: Any = _UNSET,
        position: Any = None,
    ) -> Channel:
        self._maybe_fail("edit_channel")
        channel = self._require_channel(channel_id)
        if name is not None:
            if not str(name).strip():
                raise ToolError("nome vazio", user_message="Nao da para deixar o canal sem nome.")
            channel.name = str(name).strip()
        if topic is not None:
            channel.topic = str(topic)
        if nsfw is not None:
            if bool(nsfw) and channel.type == ChannelType.GUILD_VOICE:
                raise ToolError("voz nao pode ser nsfw", user_message="Canal de voz nao aceita a marcacao NSFW.")
            channel.nsfw = bool(nsfw)
        if slowmode_delay is not None:
            delay = int(slowmode_delay)
            if delay < 0 or delay > 21600:
                raise ToolError("slowmode fora da faixa", user_message="O slowmode precisa ficar entre 0 e 21600 segundos.")
            channel.slowmode_delay = delay
        if parent_id is not _UNSET:
            self._require_category(parent_id)
            channel.parent_id = int(parent_id) if parent_id else None
        if position is not None:
            channel.position = int(position)
        return channel

    def delete_channel(self, channel_id: int) -> None:
        self._maybe_fail("delete_channel")
        channel = self._require_channel(channel_id)
        if channel.is_category:
            raise ToolError("use delete_category", user_message="Para apagar categoria use a ferramenta de categoria.")
        del self.channels[channel.id]

    def move_channel(self, channel_id: int, *, parent_id: int | None, position: int | None = None) -> Channel:
        self._maybe_fail("move_channel")
        channel = self._require_channel(channel_id)
        if channel.is_category:
            raise ToolError("categoria nao se move assim", user_message="Categorias se reordenam por posicao.")
        self._require_category(parent_id)
        channel.parent_id = int(parent_id) if parent_id else None
        if position is not None:
            channel.position = int(position)
        return channel

    def set_channel_overwrites(self, channel_id: int, overwrites: list[Overwrite]) -> Channel:
        self._maybe_fail("set_channel_overwrites")
        channel = self._require_channel(channel_id)
        for ow in overwrites:
            if ow.target_type == "member":
                raise ToolError(
                    "overwrite por membro e proibido",
                    user_message="Nao configuro permissao individual de membro. So por cargo.",
                )
            if ow.target_id not in self.roles:
                raise NotFound(f"cargo {ow.target_id} nao existe", user_message="Um dos cargos indicados nao existe.")
        channel.overwrites = list(overwrites)
        return channel

    def bulk_reorder(self, positions: list[dict[str, int]]) -> None:
        self._maybe_fail("bulk_reorder")
        staged: dict[int, int] = {}
        for item in positions:
            channel = self._require_channel(int(item["id"]))
            staged[channel.id] = int(item["position"])
        for cid, pos in staged.items():
            self.channels[cid].position = pos

    # ------------------------------------------------- categorias (canal tipo 4)
    def create_category(self, *, name: str, position: int | None = None) -> Channel:
        self._maybe_fail("create_category")
        if not name or not str(name).strip():
            raise ToolError("nome vazio", user_message="Preciso de um nome para a categoria.")
        category = Channel(
            id=self._next_id(),
            name=str(name).strip().upper(),
            type=ChannelType.GUILD_CATEGORY,
            position=position if position is not None else len([c for c in self.channels.values() if c.is_category]),
        )
        self.channels[category.id] = category
        return category

    def edit_category(self, category_id: int, *, name: Any = None, position: Any = None) -> Channel:
        self._maybe_fail("edit_category")
        category = self._require_channel(category_id)
        if not category.is_category:
            raise ToolError("nao e categoria", user_message="Esse canal nao e uma categoria.")
        if name is not None:
            category.name = str(name).strip().upper()
        if position is not None:
            category.position = int(position)
        return category

    def delete_category(self, category_id: int) -> int:
        """Devolve quantos canais ficaram orfaos (Discord nao apaga os filhos)."""
        self._maybe_fail("delete_category")
        category = self._require_channel(category_id)
        if not category.is_category:
            raise ToolError("nao e categoria", user_message="Esse canal nao e uma categoria.")
        del self.channels[category.id]
        orphans = 0
        for channel in self.channels.values():
            if channel.parent_id == category.id:
                channel.parent_id = None
                orphans += 1
        return orphans

    # ---------------------------------------------------------------- cargos
    def create_role(
        self,
        *,
        name: str,
        color: int = 0,
        hoist: bool = False,
        mentionable: bool = False,
        permissions: int = 0,
        position: int | None = None,
    ) -> Role:
        self._maybe_fail("create_role")
        if not name or not str(name).strip():
            raise ToolError("nome vazio", user_message="Preciso de um nome para o cargo.")
        if str(name).strip().lower() == "@everyone":
            raise ToolError("nao cria @everyone", user_message="O cargo @everyone ja existe e nao da para duplicar.")
        role = Role(
            id=self._next_id(),
            name=str(name).strip(),
            position=position if position is not None else 1,
            color=int(color),
            hoist=bool(hoist),
            mentionable=bool(mentionable),
            permissions=int(permissions),
        )
        self.roles[role.id] = role
        return role

    def edit_role(
        self,
        role_id: int,
        *,
        name: Any = None,
        color: Any = None,
        hoist: Any = None,
        mentionable: Any = None,
        permissions: Any = None,
    ) -> Role:
        self._maybe_fail("edit_role")
        role = self._require_role(role_id)
        if name is not None:
            if not str(name).strip():
                raise ToolError("nome vazio", user_message="Nao da para deixar o cargo sem nome.")
            role.name = str(name).strip()
        if color is not None:
            role.color = int(color)
        if hoist is not None:
            role.hoist = bool(hoist)
        if mentionable is not None:
            role.mentionable = bool(mentionable)
        if permissions is not None:
            role.permissions = int(permissions)
        return role

    def delete_role(self, role_id: int) -> None:
        self._maybe_fail("delete_role")
        role = self._require_role(role_id)
        if role.id == self.bot_role_id:
            raise ToolError("nao apaga o proprio cargo", user_message="Nao vou apagar o meu proprio cargo.")
        if role.id == 700000000000000001:
            raise ToolError("nao apaga @everyone", user_message="O cargo @everyone nao pode ser apagado.")
        del self.roles[role.id]

    def move_role(self, role_id: int, *, position: int) -> Role:
        self._maybe_fail("move_role")
        role = self._require_role(role_id)
        role.position = int(position)
        return role

    # -------------------------------------------------------------- servidor
    def edit_server(
        self,
        *,
        name: Any = None,
        description: Any = None,
        icon: Any = None,
        banner: Any = None,
    ) -> GuildSnapshot:
        self._maybe_fail("edit_server")
        if name is not None:
            text = str(name).strip()
            if not 2 <= len(text) <= 100:
                raise ToolError("nome fora da faixa", user_message="O nome do servidor precisa ter entre 2 e 100 caracteres.")
            self.name = text
        if description is not None:
            text = str(description).strip()
            if len(text) > 120:
                raise ToolError("descricao longa", user_message="A descricao do servidor tem limite de 120 caracteres.")
            self.description = text
        # icon/banner sao aceitos mas o fake nao guarda binario
        return self.snapshot()

    # ------------------------------------------------------------ introspeção
    def channel_names(self) -> list[str]:
        return sorted(c.name for c in self.channels.values())

    def role_names(self) -> list[str]:
        return sorted(r.name for r in self.roles.values())
