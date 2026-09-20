"""Porta de saida para o Discord.

O resto do codigo so conhece este Protocol. Assim da para testar com um gateway
em memoria e trocar por discord.py em producao sem tocar nas ferramentas.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .models import Channel, GuildSnapshot, Overwrite, Role


@runtime_checkable
class GuildGateway(Protocol):
    """Operacoes estruturais de UM servidor. Nao existe metodo de trocar de guild."""

    guild_id: int

    # -- leitura ------------------------------------------------------------
    def snapshot(self) -> GuildSnapshot: ...
    def get_channel(self, channel_id: int) -> Channel | None: ...
    def get_role(self, role_id: int) -> Role | None: ...

    # -- canais -------------------------------------------------------------
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
    ) -> Channel: ...

    def edit_channel(
        self,
        channel_id: int,
        *,
        name: str | None = None,
        topic: str | None = None,
        nsfw: bool | None = None,
        slowmode_delay: int | None = None,
        parent_id: int | None = ...,  # type: ignore[assignment]
        position: int | None = None,
    ) -> Channel: ...

    def delete_channel(self, channel_id: int) -> None: ...

    def move_channel(self, channel_id: int, *, parent_id: int | None, position: int | None = None) -> Channel: ...

    def set_channel_overwrites(self, channel_id: int, overwrites: list[Overwrite]) -> Channel: ...

    def bulk_reorder(self, positions: list[dict[str, int]]) -> None: ...

    # -- cargos -------------------------------------------------------------
    def create_role(
        self,
        *,
        name: str,
        color: int = 0,
        hoist: bool = False,
        mentionable: bool = False,
        permissions: int = 0,
        position: int | None = None,
    ) -> Role: ...

    def edit_role(
        self,
        role_id: int,
        *,
        name: str | None = None,
        color: int | None = None,
        hoist: bool | None = None,
        mentionable: bool | None = None,
        permissions: int | None = None,
    ) -> Role: ...

    def delete_role(self, role_id: int) -> None: ...

    def move_role(self, role_id: int, *, position: int) -> Role: ...

    # -- servidor -----------------------------------------------------------
    def edit_server(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        icon: bytes | None = None,
        banner: bytes | None = None,
    ) -> GuildSnapshot: ...


def as_dict(value: Any) -> dict[str, Any]:
    """Normaliza retorno de ferramenta para JSON do modelo."""
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return {"result": value}
