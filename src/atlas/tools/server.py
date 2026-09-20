"""Ferramenta de nivel de servidor."""

from __future__ import annotations

from typing import Any

from ..models import Perm
from ..permissions import require_bot_permission
from .base import Tool, ToolContext


def _edit_server(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_GUILD, what="alterar o servidor")

    if not any(k in params for k in ("name", "description")):
        raise ValueError("nada para alterar")

    name = params.get("name")
    if name is not None:
        name = str(name).strip()
        if not 2 <= len(name) <= ctx.limits.max_server_name_len:
            raise ValueError(
                f"nome fora da faixa (2 a {ctx.limits.max_server_name_len} caracteres)"
            )

    description = params.get("description")
    if description is not None:
        description = str(description).strip()
        if len(description) > ctx.limits.max_server_description:
            raise ValueError(f"descricao acima de {ctx.limits.max_server_description} caracteres")

    snap = ctx.gateway.edit_server(name=name, description=description)
    ctx.snapshot = snap
    return {"server": {"name": snap.name, "description": snap.description}}


def _verify_server(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    snap = ctx.refresh()
    if "name" in params and params["name"] is not None:
        if snap.name != str(params["name"]).strip():
            return False
    if "description" in params and params["description"] is not None:
        if snap.description != str(params["description"]).strip():
            return False
    return True


SERVER_TOOLS: list[Tool] = [
    Tool(
        name="edit_server",
        description=(
            "Altera nome e/ou descricao do servidor atual. Icone e banner precisam de upload de imagem "
            "e nao sao suportados por esta ferramenta."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Novo nome, 2 a 100 caracteres."},
                "description": {"type": "string", "description": "Descricao/comunidade, ate 120 caracteres."},
            },
            "required": [],
        },
        handler=_edit_server,
        requires=Perm.MANAGE_GUILD,
        verify=_verify_server,
        label=lambda p: "editar servidor",
    ),
]
