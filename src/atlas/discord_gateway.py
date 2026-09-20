"""Gateway real, sobre discord.py.

discord.py e assincrono e o nucleo do agente e sincrono (o que o torna testavel).
A ponte e feita com `run_coroutine_threadsafe`: o agente roda numa thread de
trabalho e cada operacao e despachada de volta para o loop do bot.
"""

from __future__ import annotations

import asyncio
from typing import Any

import discord

from .errors import GatewayError, NotFound, ToolError
from .models import Channel, ChannelType, GuildSnapshot, Overwrite, Perm, Role

_TIMEOUT = 30.0


class DiscordGateway:
    """Implementa o Protocol GuildGateway para UM discord.Guild fixo."""

    def __init__(self, guild: discord.Guild, loop: asyncio.AbstractEventLoop) -> None:
        self.guild = guild
        self.guild_id = guild.id
        self._loop = loop

    # ---------------------------------------------------------------- ponte
    def _run(self, coro: Any) -> Any:
        try:
            return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=_TIMEOUT)
        except discord.Forbidden as exc:
            raise GatewayError(
                f"discord proibiu: {exc}",
                user_message="O Discord negou essa operacao. Provavelmente falta permissao ao meu cargo.",
            ) from exc
        except discord.NotFound as exc:
            raise NotFound(f"discord nao achou: {exc}", user_message="Esse item sumiu do servidor.") from exc
        except discord.HTTPException as exc:
            raise GatewayError(
                f"discord HTTP {exc.status}: {exc}",
                user_message=f"A API do Discord recusou (HTTP {exc.status}).",
            ) from exc
        except TimeoutError as exc:  # pragma: no cover
            raise GatewayError("timeout na API do Discord", user_message="A API do Discord demorou demais.") from exc

    # ------------------------------------------------------------ conversao
    @staticmethod
    def _role(role: discord.Role) -> Role:
        return Role(
            id=role.id,
            name=role.name,
            position=role.position,
            color=role.colour.value if role.colour else 0,
            permissions=role.permissions.value,
            hoist=role.hoist,
            mentionable=role.mentionable,
            managed=role.managed,
        )

    @staticmethod
    def _channel_type_value(raw: Any) -> int:
        """discord.ChannelType e um Enum (nao IntEnum) a partir do discord.py 2.x.

        Aceita Enum, int e None para nao depender da versao da biblioteca.
        """
        value = getattr(raw, "value", raw)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _channel(cls, channel: discord.abc.GuildChannel, *, is_category: bool = False) -> Channel:
        ctype = int(ChannelType.GUILD_CATEGORY) if is_category else cls._channel_type_value(getattr(channel, "type", 0))
        parent = getattr(channel, "category", None)
        return Channel(
            id=channel.id,
            name=channel.name,
            type=int(ctype),
            position=getattr(channel, "position", 0) or 0,
            parent_id=parent.id if parent is not None else None,
            topic=getattr(channel, "topic", None),
            nsfw=bool(getattr(channel, "nsfw", False)),
            slowmode_delay=int(getattr(channel, "slowmode_delay", 0) or 0),
            overwrites=[
                Overwrite(
                    target_id=target.id,
                    target_type="role" if isinstance(target, discord.Role) else "member",
                    allow=pair.allow.value,
                    deny=pair.deny.value,
                )
                for target, pair in getattr(channel, "overwrites", {}).items()
            ],
        )

    # -------------------------------------------------------------- leitura
    def snapshot(self) -> GuildSnapshot:
        me = self.guild.me
        bot_role = me.top_role if me is not None else None
        channels = [self._channel(c) for c in self.guild.text_channels + self.guild.voice_channels]
        channels += [self._channel(c, is_category=True) for c in self.guild.categories]
        # forum e announcement nao entram nas listas acima
        for channel in self.guild.channels:
            if channel.id not in {c.id for c in channels}:
                channels.append(self._channel(channel))
        return GuildSnapshot(
            id=self.guild.id,
            name=self.guild.name,
            owner_id=self.guild.owner_id or 0,
            bot_role_id=bot_role.id if bot_role else 0,
            bot_permissions=me.guild_permissions.value if me is not None else 0,
            description=self.guild.description,
            channels=channels,
            roles=[self._role(r) for r in self.guild.roles],
        )

    def get_channel(self, channel_id: int) -> Channel | None:
        channel = self.guild.get_channel(int(channel_id))
        if channel is None:
            return None
        if isinstance(channel, discord.CategoryChannel):
            return self._channel(channel, is_category=True)
        return self._channel(channel)

    def get_role(self, role_id: int) -> Role | None:
        role = self.guild.get_role(int(role_id))
        return self._role(role) if role else None

    def _raw_channel(self, channel_id: int) -> discord.abc.GuildChannel:
        channel = self.guild.get_channel(int(channel_id))
        if channel is None:
            raise NotFound(f"canal {channel_id}", user_message="Esse canal nao existe mais.")
        return channel

    def _raw_category(self, category_id: int | None) -> discord.CategoryChannel | None:
        if not category_id:
            return None
        category = self.guild.get_channel(int(category_id))
        if not isinstance(category, discord.CategoryChannel):
            raise ToolError("nao e categoria", user_message="Esse ID nao e de uma categoria.")
        return category

    # --------------------------------------------------------------- canais
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
        category = self._raw_category(parent_id)
        kwargs: dict[str, Any] = {"name": name, "category": category, "position": position}
        if type == ChannelType.GUILD_VOICE:
            created = self._run(self.guild.create_voice_channel(**kwargs))
        elif type in (ChannelType.GUILD_ANNOUNCEMENT, ChannelType.GUILD_FORUM):
            kwargs["type"] = discord.ChannelType(type)
            kwargs.pop("topic", None)
            if type == ChannelType.GUILD_FORUM:
                kwargs.pop("nsfw", None)
            created = self._run(self.guild.create_channel(**kwargs))
        else:
            created = self._run(
                self.guild.create_text_channel(topic=topic, nsfw=nsfw, slowmode_delay=slowmode_delay, **kwargs)
            )
        return self._channel(created)

    def edit_channel(
        self,
        channel_id: int,
        *,
        name: Any = None,
        topic: Any = None,
        nsfw: Any = None,
        slowmode_delay: Any = None,
        parent_id: Any = ...,
        position: Any = None,
    ) -> Channel:
        channel = self._raw_channel(channel_id)
        kwargs: dict[str, Any] = {}
        if name is not None:
            kwargs["name"] = name
        if topic is not None:
            kwargs["topic"] = topic
        if nsfw is not None:
            kwargs["nsfw"] = nsfw
        if slowmode_delay is not None:
            kwargs["slowmode_delay"] = slowmode_delay
        if parent_id is not ...:
            kwargs["category"] = self._raw_category(parent_id)
        if position is not None:
            kwargs["position"] = position
        if not kwargs:
            raise ToolError("nada para alterar", user_message="Nao recebi nenhuma mudanca para aplicar.")
        updated = self._run(channel.edit(**kwargs))
        return self._channel(updated or channel)

    def delete_channel(self, channel_id: int) -> None:
        self._run(self._raw_channel(channel_id).delete())

    def move_channel(self, channel_id: int, *, parent_id: int | None, position: int | None = None) -> Channel:
        channel = self._raw_channel(channel_id)
        self._run(channel.edit(category=self._raw_category(parent_id), position=position))
        return self._channel(channel)

    def set_channel_overwrites(self, channel_id: int, overwrites: list[Overwrite]) -> Channel:
        channel = self._raw_channel(channel_id)
        for ow in overwrites:
            if ow.target_type != "role":
                raise ToolError(
                    "overwrite por membro",
                    user_message="Nao configuro permissao individual de membro.",
                )
            role = self.guild.get_role(ow.target_id)
            if role is None:
                raise NotFound(f"cargo {ow.target_id}", user_message="Um dos cargos nao existe.")
            # discord.py nao aceita misturar `overwrite=True` com allow=/deny=;
            # o par precisa virar um PermissionOverwrite.
            pair = discord.PermissionOverwrite.from_pair(
                discord.Permissions(ow.allow), discord.Permissions(ow.deny)
            )
            self._run(channel.set_permissions(role, overwrite=pair))
        return self._channel(channel)

    def bulk_reorder(self, positions: list[dict[str, int]]) -> None:
        pairs = []
        for item in positions:
            channel = self.guild.get_channel(int(item["id"]))
            if channel is None:
                raise NotFound(f"canal {item['id']}", user_message="Um dos canais da reordenacao nao existe.")
            pairs.append((channel, int(item["position"])))
        self._run(self.guild.edit_channel_positions(pairs))

    # ---------------------------------------------------------- categorias
    def create_category(self, *, name: str, position: int | None = None) -> Channel:
        created = self._run(self.guild.create_category(name, position=position))
        return self._channel(created, is_category=True)

    def edit_category(self, category_id: int, *, name: Any = None, position: Any = None) -> Channel:
        category = self._raw_category(category_id)
        assert category is not None
        kwargs: dict[str, Any] = {}
        if name is not None:
            kwargs["name"] = name
        if position is not None:
            kwargs["position"] = position
        if not kwargs:
            raise ToolError("nada para alterar", user_message="Nao recebi nenhuma mudanca.")
        updated = self._run(category.edit(**kwargs))
        return self._channel(updated or category, is_category=True)

    def delete_category(self, category_id: int) -> int:
        category = self._raw_category(category_id)
        assert category is not None
        orphans = len(category.channels)
        self._run(category.delete())
        return orphans

    # --------------------------------------------------------------- cargos
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
        created = self._run(
            self.guild.create_role(
                name=name,
                colour=discord.Colour(color),
                hoist=hoist,
                mentionable=mentionable,
                permissions=discord.Permissions(permissions),
            )
        )
        if position is not None:
            self._run(created.edit(position=position))
        return self._role(created)

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
        role = self.guild.get_role(int(role_id))
        if role is None:
            raise NotFound(f"cargo {role_id}", user_message="Esse cargo nao existe mais.")
        kwargs: dict[str, Any] = {}
        if name is not None:
            kwargs["name"] = name
        if color is not None:
            kwargs["colour"] = discord.Colour(int(color))
        if hoist is not None:
            kwargs["hoist"] = hoist
        if mentionable is not None:
            kwargs["mentionable"] = mentionable
        if permissions is not None:
            kwargs["permissions"] = discord.Permissions(int(permissions))
        if not kwargs:
            raise ToolError("nada para alterar", user_message="Nao recebi nenhuma mudanca.")
        updated = self._run(role.edit(**kwargs))
        return self._role(updated or role)

    def delete_role(self, role_id: int) -> None:
        role = self.guild.get_role(int(role_id))
        if role is None:
            raise NotFound(f"cargo {role_id}", user_message="Esse cargo nao existe mais.")
        self._run(role.delete())

    def move_role(self, role_id: int, *, position: int) -> Role:
        role = self.guild.get_role(int(role_id))
        if role is None:
            raise NotFound(f"cargo {role_id}", user_message="Esse cargo nao existe mais.")
        self._run(role.edit(position=int(position)))
        return self._role(role)

    # ------------------------------------------------------------- servidor
    def edit_server(
        self,
        *,
        name: Any = None,
        description: Any = None,
        icon: Any = None,
        banner: Any = None,
    ) -> GuildSnapshot:
        kwargs: dict[str, Any] = {}
        if name is not None:
            kwargs["name"] = name
        if description is not None:
            kwargs["description"] = description
        if icon is not None:
            kwargs["icon"] = icon
        if banner is not None:
            kwargs["banner"] = banner
        if not kwargs:
            raise ToolError("nada para alterar", user_message="Nao recebi nenhuma mudanca.")
        self._run(self.guild.edit(**kwargs))
        return self.snapshot()
