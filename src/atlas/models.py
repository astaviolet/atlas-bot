"""Modelos de dominio. Sao independentes do discord.py para permitir teste com fake."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class ChannelType(IntEnum):
    GUILD_TEXT = 0
    GUILD_VOICE = 2
    GUILD_CATEGORY = 4
    GUILD_ANNOUNCEMENT = 5
    GUILD_FORUM = 15


CHANNEL_TYPE_LABEL = {
    ChannelType.GUILD_TEXT: "texto",
    ChannelType.GUILD_VOICE: "voz",
    ChannelType.GUILD_CATEGORY: "categoria",
    ChannelType.GUILD_ANNOUNCEMENT: "anuncio",
    ChannelType.GUILD_FORUM: "forum",
}

# nomes aceitos pelo modelo -> tipo real
CHANNEL_TYPE_ALIAS: dict[str, ChannelType] = {
    "text": ChannelType.GUILD_TEXT,
    "texto": ChannelType.GUILD_TEXT,
    "voice": ChannelType.GUILD_VOICE,
    "voz": ChannelType.GUILD_VOICE,
    "category": ChannelType.GUILD_CATEGORY,
    "categoria": ChannelType.GUILD_CATEGORY,
    "announcement": ChannelType.GUILD_ANNOUNCEMENT,
    "anuncio": ChannelType.GUILD_ANNOUNCEMENT,
    "news": ChannelType.GUILD_ANNOUNCEMENT,
    "forum": ChannelType.GUILD_FORUM,
    "forun": ChannelType.GUILD_FORUM,
}


class Perm(IntEnum):
    """Bits de permissao do Discord que este agente entende."""

    CREATE_INSTANT_INVITE = 1 << 0
    KICK_MEMBERS = 1 << 1
    BAN_MEMBERS = 1 << 2
    ADMINISTRATOR = 1 << 3
    MANAGE_CHANNELS = 1 << 4
    MANAGE_GUILD = 1 << 5
    VIEW_CHANNEL = 1 << 10
    SEND_MESSAGES = 1 << 11
    SEND_TTS_MESSAGES = 1 << 12
    MANAGE_MESSAGES = 1 << 13
    EMBED_LINKS = 1 << 14
    ATTACH_FILES = 1 << 15
    READ_MESSAGE_HISTORY = 1 << 16
    MENTION_EVERYONE = 1 << 17
    CONNECT = 1 << 20
    SPEAK = 1 << 21
    MANAGE_ROLES = 1 << 28
    MANAGE_WEBHOOKS = 1 << 29
    MANAGE_EVENTS = 1 << 33
    MODERATE_MEMBERS = 1 << 40


# Permissoes que o agente jamais concede, mesmo que a IA peca.
NEVER_GRANTABLE: frozenset[Perm] = frozenset(
    {
        Perm.BAN_MEMBERS,
        Perm.KICK_MEMBERS,
        Perm.MODERATE_MEMBERS,
        Perm.MENTION_EVERYONE,
        Perm.ADMINISTRATOR,
    }
)

# Mapa nome legivel -> bit. Usado para validar o que o modelo pediu.
PERM_BY_NAME: dict[str, Perm] = {p.name.lower(): p for p in Perm}
PERM_ALIASES: dict[str, str] = {
    "gerenciar_canais": "manage_channels",
    "gerenciar_cargos": "manage_roles",
    "gerenciar_servidor": "manage_guild",
    "ver_canal": "view_channel",
    "enviar_mensagens": "send_messages",
    "gerenciar_mensagens": "manage_messages",
    "ler_historico": "read_message_history",
    "conectar": "connect",
    "falar": "speak",
}


@dataclass
class Role:
    id: int
    name: str
    position: int = 0
    color: int = 0
    permissions: int = 0
    hoist: bool = False
    mentionable: bool = False
    managed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "position": self.position,
            "color": self.color,
            "hoist": self.hoist,
            "mentionable": self.mentionable,
            "managed": self.managed,
        }


@dataclass
class Overwrite:
    target_id: int
    target_type: str  # "role" | "member"
    allow: int = 0
    deny: int = 0


@dataclass
class Channel:
    id: int
    name: str
    type: int = ChannelType.GUILD_TEXT
    position: int = 0
    parent_id: int | None = None
    topic: str | None = None
    nsfw: bool = False
    slowmode_delay: int = 0
    overwrites: list[Overwrite] = field(default_factory=list)

    @property
    def is_category(self) -> bool:
        return self.type == ChannelType.GUILD_CATEGORY

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "type": CHANNEL_TYPE_LABEL.get(self.type, str(self.type)),
            "position": self.position,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "topic": self.topic,
            "nsfw": self.nsfw,
            "slowmode_delay": self.slowmode_delay,
            "overwrites": len(self.overwrites),
        }


@dataclass
class GuildSnapshot:
    """Estado relevante do servidor. E o que vai no contexto do modelo."""

    id: int
    name: str
    owner_id: int
    bot_role_id: int
    bot_permissions: int
    description: str | None = None
    channels: list[Channel] = field(default_factory=list)
    roles: list[Role] = field(default_factory=list)

    @property
    def bot_role(self) -> Role | None:
        for role in self.roles:
            if role.id == self.bot_role_id:
                return role
        return None

    def category_channels(self) -> list[Channel]:
        return [c for c in self.channels if c.is_category]

    def find_channel(self, channel_id: int) -> Channel | None:
        for c in self.channels:
            if c.id == channel_id:
                return c
        return None

    def find_role(self, role_id: int) -> Role | None:
        for r in self.roles:
            if r.id == role_id:
                return r
        return None

    def compact(self) -> dict[str, Any]:
        """Versao enxuta para o prompt. Sem dado de membro."""
        return {
            "guild_id": str(self.id),
            "name": self.name,
            "description": self.description,
            "roles": [r.to_dict() for r in sorted(self.roles, key=lambda r: -r.position)],
            "categories": [c.to_dict() for c in self.category_channels()],
            "channels": [c.to_dict() for c in self.channels if not c.is_category],
        }
