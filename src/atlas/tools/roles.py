"""Ferramentas de cargos. Toda mutacao passa pela checagem de hierarquia."""

from __future__ import annotations

from typing import Any

from ..errors import NotFound, ToolError
from ..models import Perm
from ..permissions import (
    normalize_color,
    reject_never_grantable,
    require_bot_permission,
    require_role_hierarchy,
    split_unknown_permissions,
)
from .base import Tool, ToolContext

_ROLE_ID = {"type": "string", "description": "ID do cargo, como veio de get_roles."}
_COLOR = {
    "type": "string",
    "description": "Cor em hexadecimal, ex: '#5865F2'. Use '#000000' para sem cor.",
}


def _resolve_role(ctx: ToolContext, params: dict[str, Any]):
    try:
        rid = int(params["role_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError("role_id invalido", user_message="Preciso do ID do cargo.") from exc
    role = ctx.snapshot.find_role(rid)
    if role is None:
        raise NotFound(f"cargo {rid}", user_message="Esse cargo nao existe no servidor.")
    return role


def _clean_name(value: Any, ctx: ToolContext) -> str:
    name = str(value or "").strip()
    if not name:
        raise ToolError("nome vazio", user_message="Preciso de um nome para o cargo.")
    if len(name) > ctx.limits.max_name_len:
        raise ToolError("nome longo", user_message=f"Nome passa de {ctx.limits.max_name_len} caracteres.")
    if name.lower() == "@everyone":
        raise ToolError("@everyone", user_message="Nao crio nem renomeio o cargo @everyone.")
    return name


def _create_role(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_ROLES, what="criar cargo")
    name = _clean_name(params.get("name"), ctx)

    if len(ctx.snapshot.roles) >= ctx.limits.max_role_count:
        raise ToolError(
            "limite de cargos",
            user_message=f"O Discord limita a {ctx.limits.max_role_count} cargos e esse servidor ja chegou la.",
        )

    try:
        color = normalize_color(params.get("color"))
    except ValueError as exc:
        raise ToolError("cor invalida", user_message=str(exc)) from exc

    permissions = int(params.get("permissions", 0) or 0)
    role = ctx.gateway.create_role(
        name=name,
        color=color,
        hoist=bool(params.get("hoist", False)),
        mentionable=bool(params.get("mentionable", False)),
        permissions=permissions,
    )
    return {"created": role.to_dict()}


def _verify_create_role(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    snap = ctx.refresh()
    name = str(params.get("name", "")).strip()
    return any(r.name == name for r in snap.roles)


def _edit_role(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_ROLES, what="editar cargo")
    role = _resolve_role(ctx, params)
    require_role_hierarchy(ctx.snapshot, role, what="editar esse cargo")

    if not any(k in params for k in ("name", "color", "hoist", "mentionable")):
        raise ToolError("nada para alterar", user_message="Voce nao me disse o que mudar nesse cargo.")

    color = None
    if "color" in params:
        try:
            color = normalize_color(params.get("color"))
        except ValueError as exc:
            raise ToolError("cor invalida", user_message=str(exc)) from exc

    updated = ctx.gateway.edit_role(
        role.id,
        name=_clean_name(params["name"], ctx) if "name" in params else None,
        color=color,
        hoist=bool(params["hoist"]) if "hoist" in params else None,
        mentionable=bool(params["mentionable"]) if "mentionable" in params else None,
    )
    return {"updated": updated.to_dict()}


def _verify_edit_role(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    snap = ctx.refresh()
    try:
        role = snap.find_role(int(params["role_id"]))
    except (KeyError, TypeError, ValueError):
        return False
    if role is None:
        return False
    if "name" in params and role.name != str(params["name"]).strip():
        return False
    if "color" in params:
        try:
            if role.color != normalize_color(params["color"]):
                return False
        except ValueError:
            return False
    return True


def _delete_role(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_ROLES, what="excluir cargo")
    role = _resolve_role(ctx, params)
    require_role_hierarchy(ctx.snapshot, role, what="excluir esse cargo")
    ctx.gateway.delete_role(role.id)
    return {"deleted": {"id": str(role.id), "name": role.name}}


def _verify_delete_role(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    snap = ctx.refresh()
    try:
        return snap.find_role(int(params["role_id"])) is None
    except (KeyError, TypeError, ValueError):
        return False


def _move_role(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_ROLES, what="mover cargo na hierarquia")
    role = _resolve_role(ctx, params)
    require_role_hierarchy(ctx.snapshot, role, what="mover esse cargo")
    try:
        position = int(params["position"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError("position invalida", user_message="Preciso da nova posicao (numero inteiro).") from exc

    bot_role = ctx.snapshot.bot_role
    if bot_role is not None and position >= bot_role.position:
        raise ToolError(
            "posicao acima do bot",
            user_message=(
                f"Colocar **{role.name}** na posicao {position} o deixaria no meu nivel ou acima. "
                f"Meu cargo esta em {bot_role.position}."
            ),
        )
    if position < 0:
        raise ToolError("posicao negativa", user_message="A posicao nao pode ser negativa.")
    moved = ctx.gateway.move_role(role.id, position=position)
    return {"moved": moved.to_dict()}


def _verify_move_role(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    snap = ctx.refresh()
    try:
        role = snap.find_role(int(params["role_id"]))
    except (KeyError, TypeError, ValueError):
        return False
    return role is not None and role.position == int(params["position"])


def _set_role_permissions(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_ROLES, what="mudar permissao de cargo")
    role = _resolve_role(ctx, params)
    require_role_hierarchy(ctx.snapshot, role, what="mudar as permissoes desse cargo")

    allow_raw, deny_raw = params.get("allow") or [], params.get("deny") or []
    allow_perms, unknown_allow = split_unknown_permissions(allow_raw)
    deny_perms, unknown_deny = split_unknown_permissions(deny_raw)

    blocked = reject_never_grantable(allow_perms)
    if blocked:
        raise ToolError(
            f"permissoes proibidas: {blocked}",
            user_message=(
                "Nao concedo " + ", ".join(f"**{b}**" for b in blocked)
                + " a um cargo. Moderacao de pessoas e mencao a @everyone ficam fora."
            ),
        )
    if not allow_perms and not deny_perms:
        raise ToolError("nada para aplicar", user_message="Nao recebi nenhuma permissao valida.")

    # parte da bitmask atual, aplica allow, remove deny
    bits = role.permissions
    for perm, ok in allow_perms.items():
        if ok:
            bits |= int(perm)
        else:
            bits &= ~int(perm)
    for perm, ok in deny_perms.items():
        if ok:
            bits &= ~int(perm)
        else:
            bits |= int(perm)

    # garantia final: nunca deixa um bit proibido ligado
    for perm in (Perm.BAN_MEMBERS, Perm.KICK_MEMBERS, Perm.MODERATE_MEMBERS,
                 Perm.MENTION_EVERYONE, Perm.ADMINISTRATOR):
        bits &= ~int(perm)

    updated = ctx.gateway.edit_role(role.id, permissions=bits)
    return {
        "updated": updated.to_dict(),
        "applied_allow": sorted(p.name.lower() for p, ok in allow_perms.items() if ok),
        "applied_deny": sorted(p.name.lower() for p, ok in deny_perms.items() if ok),
        "ignored_unknown": sorted(set(unknown_allow) | set(unknown_deny)),
        "final_bits": updated.permissions,
    }


def _verify_role_permissions(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    snap = ctx.refresh()
    try:
        role = snap.find_role(int(params["role_id"]))
    except (KeyError, TypeError, ValueError):
        return False
    return role is not None and role.permissions == int(data["final_bits"])


ROLE_TOOLS: list[Tool] = [
    Tool(
        name="create_role",
        description=(
            "Cria um cargo. Ele nasce ABAIXO do cargo do bot na hierarquia, que e o que o Discord permite."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do cargo."},
                "color": _COLOR,
                "hoist": {"type": "boolean", "description": "Mostra o cargo separado na lista de membros."},
                "mentionable": {"type": "boolean", "description": "Permite que o cargo seja mencionavel."},
            },
            "required": ["name"],
        },
        handler=_create_role,
        requires=Perm.MANAGE_ROLES,
        verify=_verify_create_role,
        label=lambda p: f"criar cargo @{p.get('name', '?')}",
    ),
    Tool(
        name="edit_role",
        description="Renomeia, muda cor, hoist ou mencionavel de um cargo abaixo do cargo do bot.",
        parameters={
            "type": "object",
            "properties": {
                "role_id": _ROLE_ID,
                "name": {"type": "string"},
                "color": _COLOR,
                "hoist": {"type": "boolean"},
                "mentionable": {"type": "boolean"},
            },
            "required": ["role_id"],
        },
        handler=_edit_role,
        requires=Perm.MANAGE_ROLES,
        verify=_verify_edit_role,
        label=lambda p: f"editar cargo {p.get('role_id', '?')}",
    ),
    Tool(
        name="delete_role",
        description="Exclui um cargo. Acao destrutiva. Nao funciona em cargo acima do bot nem em cargo de integracao.",
        parameters={
            "type": "object",
            "properties": {"role_id": _ROLE_ID},
            "required": ["role_id"],
        },
        handler=_delete_role,
        destructive=True,
        requires=Perm.MANAGE_ROLES,
        verify=_verify_delete_role,
        label=lambda p: f"excluir cargo {p.get('role_id', '?')}",
    ),
    Tool(
        name="move_role",
        description="Muda a posicao de um cargo na hierarquia. Nunca acima do cargo do bot.",
        parameters={
            "type": "object",
            "properties": {
                "role_id": _ROLE_ID,
                "position": {"type": "integer", "description": "Nova posicao. 1 e o nivel mais baixo util."},
            },
            "required": ["role_id", "position"],
        },
        handler=_move_role,
        requires=Perm.MANAGE_ROLES,
        verify=_verify_move_role,
        label=lambda p: f"mover cargo {p.get('role_id', '?')} para posicao {p.get('position', '?')}",
    ),
    Tool(
        name="set_role_permissions",
        description=(
            "Concede ou remove permissoes de um cargo. Nomes validos: manage_channels, manage_roles, "
            "manage_guild, view_channel, send_messages, manage_messages, read_message_history, "
            "embed_links, attach_files, connect, speak, manage_webhooks, manage_events. "
            "Proibido: ban_members, kick_members, moderate_members, mention_everyone, administrator."
        ),
        parameters={
            "type": "object",
            "properties": {
                "role_id": _ROLE_ID,
                "allow": {"type": "array", "description": "Permissoes a conceder.", "items": {"type": "string"}},
                "deny": {"type": "array", "description": "Permissoes a remover.", "items": {"type": "string"}},
            },
            "required": ["role_id"],
        },
        handler=_set_role_permissions,
        requires=Perm.MANAGE_ROLES,
        verify=_verify_role_permissions,
        label=lambda p: f"permissoes do cargo {p.get('role_id', '?')}",
    ),
]
