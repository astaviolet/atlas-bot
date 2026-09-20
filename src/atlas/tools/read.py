"""Ferramentas de leitura. Nao mutam nada e nunca expoe dado de membro."""

from __future__ import annotations

from typing import Any

from ..errors import NotFound
from ..models import CHANNEL_TYPE_LABEL
from .base import Tool

_ID_PARAM = {"type": "string", "description": "ID do objeto, como veio de get_channels/get_roles."}


def _get_server_info(ctx, params: dict[str, Any]) -> dict[str, Any]:
    snap = ctx.refresh()
    data = snap.compact()
    bot_role = snap.bot_role
    data["bot"] = {
        "role_name": bot_role.name if bot_role else None,
        "role_position": bot_role.position if bot_role else None,
        "note": "nao posso administrar cargos com position >= ao meu",
    }
    return data


def _get_channels(ctx, params: dict[str, Any]) -> dict[str, Any]:
    snap = ctx.refresh()
    channels = [c for c in snap.channels if not c.is_category]
    return {
        "total": len(channels),
        "channels": [c.to_dict() for c in sorted(channels, key=lambda c: (c.position, c.name))],
    }


def _get_categories(ctx, params: dict[str, Any]) -> dict[str, Any]:
    snap = ctx.refresh()
    cats = snap.category_channels()
    out = []
    for cat in sorted(cats, key=lambda c: c.position):
        children = [c for c in snap.channels if c.parent_id == cat.id]
        out.append({**cat.to_dict(), "child_count": len(children),
                    "children": [c.name for c in sorted(children, key=lambda c: c.position)]})
    return {"total": len(out), "categories": out}


def _get_channel(ctx, params: dict[str, Any]) -> dict[str, Any]:
    snap = ctx.refresh()
    try:
        cid = int(params["channel_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NotFound("channel_id invalido", user_message="Preciso do ID do canal.") from exc
    channel = snap.find_channel(cid)
    if channel is None:
        raise NotFound(f"canal {cid}", user_message="Nao achei esse canal no servidor.")
    data = channel.to_dict()
    data["type_raw"] = channel.type
    data["type_label"] = CHANNEL_TYPE_LABEL.get(channel.type, str(channel.type))
    data["overwrites"] = [
        {"target_id": str(ow.target_id), "target_type": ow.target_type, "allow": ow.allow, "deny": ow.deny}
        for ow in channel.overwrites
    ]
    return data


def _get_roles(ctx, params: dict[str, Any]) -> dict[str, Any]:
    snap = ctx.refresh()
    bot_role = snap.bot_role
    bot_pos = bot_role.position if bot_role else 0
    roles = sorted(snap.roles, key=lambda r: -r.position)
    return {
        "total": len(roles),
        "bot_role_position": bot_pos,
        "roles": [{**r.to_dict(), "editable_by_bot": r.position < bot_pos and not r.managed} for r in roles],
    }


def _get_role(ctx, params: dict[str, Any]) -> dict[str, Any]:
    snap = ctx.refresh()
    try:
        rid = int(params["role_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NotFound("role_id invalido", user_message="Preciso do ID do cargo.") from exc
    role = snap.find_role(rid)
    if role is None:
        raise NotFound(f"cargo {rid}", user_message="Nao achei esse cargo no servidor.")
    bot_role = snap.bot_role
    bot_pos = bot_role.position if bot_role else 0
    data = role.to_dict()
    data["permissions_bits"] = role.permissions
    data["editable_by_bot"] = role.position < bot_pos and not role.managed and role.id != snap.bot_role_id
    if not data["editable_by_bot"]:
        data["block_reason"] = "gerenciado por integracao" if role.managed else "esta acima ou no nivel do meu cargo"
    return data


READ_TOOLS: list[Tool] = [
    Tool(
        name="get_server_info",
        description=(
            "Retorna o estado atual do servidor: nome, descricao, categorias, canais, cargos e a "
            "posicao do cargo do bot. Use SEMPRE antes de planejar alteracoes."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_get_server_info,
    ),
    Tool(
        name="get_channels",
        description="Lista todos os canais que nao sao categoria, com id, tipo, posicao e categoria pai.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_get_channels,
    ),
    Tool(
        name="get_categories",
        description="Lista as categorias com a contagem e os nomes dos canais filhos de cada uma.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_get_categories,
    ),
    Tool(
        name="get_channel",
        description="Detalha um canal especifico, incluindo as sobrescritas de permissao atuais.",
        parameters={
            "type": "object",
            "properties": {"channel_id": _ID_PARAM},
            "required": ["channel_id"],
        },
        handler=_get_channel,
    ),
    Tool(
        name="get_roles",
        description=(
            "Lista os cargos em ordem de hierarquia e marca quais o bot pode editar "
            "(editable_by_bot). Nunca tente editar um cargo com editable_by_bot=false."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_get_roles,
    ),
    Tool(
        name="get_role",
        description="Detalha um cargo, incluindo se o bot pode ou nao edita-lo e o motivo se nao puder.",
        parameters={
            "type": "object",
            "properties": {"role_id": _ID_PARAM},
            "required": ["role_id"],
        },
        handler=_get_role,
    ),
]
