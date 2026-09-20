"""Ferramentas de canais e categorias."""

from __future__ import annotations

from typing import Any

from ..errors import NotFound, ToolError
from ..models import CHANNEL_TYPE_ALIAS, ChannelType, Overwrite, Perm
from ..permissions import (
    reject_never_grantable,
    require_bot_permission,
    split_unknown_permissions,
)
from .base import Tool, ToolContext, confirmar_mudanca

_NAME = {"type": "string", "description": "Nome do canal. Use minusculas e hifens para canais de texto."}
_TYPE = {
    "type": "string",
    "description": "Tipo do canal: text, voice, announcement ou forum.",
    "enum": ["text", "voice", "announcement", "forum"],
}
_CATEGORY_ID = {"type": "string", "description": "ID da categoria pai. Omita para deixar fora de categoria."}
_CHANNEL_ID = {"type": "string", "description": "ID do canal."}


def _clean_name(value: Any, ctx: ToolContext) -> str:
    name = str(value or "").strip()
    if not name:
        raise ToolError("nome vazio", user_message="Preciso de um nome.")
    if len(name) > ctx.limits.max_name_len:
        raise ToolError("nome longo", user_message=f"Nome com mais de {ctx.limits.max_name_len} caracteres.")
    return name


def _resolve_type(value: Any) -> int:
    key = str(value or "text").strip().lower()
    ctype = CHANNEL_TYPE_ALIAS.get(key)
    if ctype is None:
        raise ToolError(
            f"tipo desconhecido {value!r}",
            user_message="Tipo de canal valido: text, voice, announcement ou forum.",
        )
    if ctype == ChannelType.GUILD_CATEGORY:
        raise ToolError("use create_category", user_message="Para categoria use create_category.")
    return int(ctype)


def _check_topic(value: Any, ctx: ToolContext) -> str | None:
    if value is None:
        return None
    topic = str(value).strip()
    if len(topic) > ctx.limits.max_topic_len:
        raise ToolError("topico longo", user_message=f"Topico passa de {ctx.limits.max_topic_len} caracteres.")
    return topic or None


def _check_slowmode(value: Any) -> int | None:
    if value is None:
        return None
    try:
        delay = int(value)
    except (TypeError, ValueError) as exc:
        raise ToolError("slowmode invalido", user_message="O slowmode precisa ser um numero de segundos.") from exc
    if not 0 <= delay <= 21600:
        raise ToolError("slowmode fora da faixa", user_message="Slowmode vai de 0 a 21600 segundos.")
    return delay


def _resolve_parent(ctx: ToolContext, params: dict[str, Any]) -> int | None:
    raw = params.get("category_id") or params.get("parent_id")
    if raw in (None, "", "none", "null"):
        return None
    try:
        parent_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise ToolError("category_id invalido", user_message="O ID da categoria nao esta valido.") from exc
    parent = ctx.snapshot.find_channel(parent_id)
    if parent is None:
        raise NotFound(f"categoria {parent_id}", user_message="Essa categoria nao existe no servidor.")
    if not parent.is_category:
        raise ToolError(
            "pai nao e categoria",
            user_message=f"**{parent.name}** nao e uma categoria, entao nao da para colocar canal dentro.",
        )
    return parent_id


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------
def _create_channel(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_CHANNELS, what="criar canal")
    name = _clean_name(params.get("name"), ctx)
    ctype = _resolve_type(params.get("type"))
    parent_id = _resolve_parent(ctx, params)
    topic = _check_topic(params.get("topic"), ctx)
    slowmode = _check_slowmode(params.get("slowmode_delay"))

    nsfw = bool(params.get("nsfw", False))
    if nsfw and ctype == ChannelType.GUILD_VOICE:
        raise ToolError("voz nao aceita nsfw", user_message="Canal de voz nao pode ser marcado como NSFW.")

    # Idempotencia (spec 13/178): pedir duas vezes o mesmo canal nao pode
    # produzir dois canais. Medido em producao antes disto: um pedido de design
    # criou "regras" e "anuncios" duas vezes porque o servidor ja os tinha.
    # Casamento exige nome + tipo + mesma categoria: "geral" de texto e "geral"
    # de voz sao coisas diferentes, e o mesmo nome em outra categoria tambem.
    for existente in ctx.snapshot.channels:
        if (
            not existente.is_category
            and existente.name == name
            and existente.type == ctype
            and existente.parent_id == parent_id
        ):
            return {
                "created": existente.to_dict(),
                "reused": True,
                "note": "ja existia um canal igual; nao criei outro",
            }

    siblings = [c for c in ctx.snapshot.channels if c.parent_id == parent_id and not c.is_category]
    if len(siblings) >= ctx.limits.max_channels_per_category:
        raise ToolError(
            "muitos canais na categoria",
            user_message=f"Essa categoria ja tem {len(siblings)} canais. Limite pratico: {ctx.limits.max_channels_per_category}.",
        )

    channel = ctx.gateway.create_channel(
        name=name, type=ctype, parent_id=parent_id, topic=topic,
        nsfw=nsfw, slowmode_delay=slowmode or 0,
    )
    return {"created": channel.to_dict()}


def _verify_create_channel(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    snap = ctx.refresh()
    name = str(params.get("name", "")).strip()
    return any(c.name == name and not c.is_category for c in snap.channels)


def _edit_channel(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_CHANNELS, what="editar canal")
    try:
        cid = int(params["channel_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError("channel_id invalido", user_message="Preciso do ID do canal.") from exc

    channel = ctx.snapshot.find_channel(cid)
    if channel is None:
        raise NotFound(f"canal {cid}", user_message="Esse canal nao existe no servidor.")
    if channel.is_category:
        raise ToolError("use edit_category", user_message="Esse item e uma categoria. Use edit_category.")

    if not any(k in params for k in ("name", "topic", "nsfw", "slowmode_delay")):
        raise ToolError("nada para alterar", user_message="Voce nao me disse o que mudar nesse canal.")

    updated = ctx.gateway.edit_channel(
        cid,
        name=_clean_name(params["name"], ctx) if "name" in params else None,
        topic=_check_topic(params.get("topic"), ctx) if "topic" in params else None,
        nsfw=bool(params["nsfw"]) if "nsfw" in params else None,
        slowmode_delay=_check_slowmode(params.get("slowmode_delay")) if "slowmode_delay" in params else None,
    )
    return {"updated": updated.to_dict()}


def _verify_edit_channel(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    snap = ctx.refresh()
    try:
        channel = snap.find_channel(int(params["channel_id"]))
    except (KeyError, TypeError, ValueError):
        return False
    if channel is None:
        return False
    if "name" in params and channel.name != str(params["name"]).strip():
        return False
    if "slowmode_delay" in params and channel.slowmode_delay != int(params["slowmode_delay"]):
        return False
    if "nsfw" in params and channel.nsfw != bool(params["nsfw"]):
        return False
    return True


def _delete_channel(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_CHANNELS, what="excluir canal")
    try:
        cid = int(params["channel_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError("channel_id invalido", user_message="Preciso do ID do canal.") from exc
    channel = ctx.snapshot.find_channel(cid)
    if channel is None:
        raise NotFound(f"canal {cid}", user_message="Esse canal ja nao existe.")
    if channel.is_category:
        raise ToolError("use delete_category", user_message="Esse item e uma categoria. Use delete_category.")
    ctx.gateway.delete_channel(cid)
    return {"deleted": {"id": str(cid), "name": channel.name}}


def _verify_delete_channel(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    try:
        cid = int(params["channel_id"])
    except (KeyError, TypeError, ValueError):
        return False
    return confirmar_mudanca(ctx, lambda s: s.find_channel(cid) is None)


def _create_category(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_CHANNELS, what="criar categoria")
    name = _clean_name(params.get("name"), ctx)

    # Categoria no Discord e sempre MAIUSCULA; comparar sem diferenciar caixa
    # evita criar "COMUNIDADE" quando ja existe "comunidade".
    for existente in ctx.snapshot.channels:
        if existente.is_category and existente.name.casefold() == name.casefold():
            return {
                "created": existente.to_dict(),
                "reused": True,
                "note": "ja existia uma categoria com esse nome; nao criei outra",
            }

    category = ctx.gateway.create_category(name=name)
    return {"created": category.to_dict()}


def _verify_create_category(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    snap = ctx.refresh()
    name = str(params.get("name", "")).strip().upper()
    return any(c.name == name and c.is_category for c in snap.channels)


def _edit_category(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_CHANNELS, what="editar categoria")
    try:
        cid = int(params["category_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError("category_id invalido", user_message="Preciso do ID da categoria.") from exc
    target = ctx.snapshot.find_channel(cid)
    if target is None:
        raise NotFound(f"categoria {cid}", user_message="Essa categoria nao existe.")
    if not target.is_category:
        raise ToolError("nao e categoria", user_message="Esse item nao e uma categoria.")
    updated = ctx.gateway.edit_category(
        cid,
        name=_clean_name(params["name"], ctx) if "name" in params else None,
        position=int(params["position"]) if params.get("position") is not None else None,
    )
    return {"updated": updated.to_dict()}


def _verify_edit_category(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    snap = ctx.refresh()
    try:
        cat = snap.find_channel(int(params["category_id"]))
    except (KeyError, TypeError, ValueError):
        return False
    if cat is None:
        return False
    if "name" in params and cat.name != str(params["name"]).strip().upper():
        return False
    return True


def _delete_category(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_CHANNELS, what="excluir categoria")
    try:
        cid = int(params["category_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError("category_id invalido", user_message="Preciso do ID da categoria.") from exc
    target = ctx.snapshot.find_channel(cid)
    if target is None:
        raise NotFound(f"categoria {cid}", user_message="Essa categoria ja nao existe.")
    if not target.is_category:
        raise ToolError("nao e categoria", user_message="Esse item nao e uma categoria.")
    orphans = ctx.gateway.delete_category(cid)
    return {
        "deleted": {"id": str(cid), "name": target.name},
        "orphaned_channels": orphans,
        "note": "o Discord nao apaga os canais filhos; eles ficam sem categoria",
    }


def _verify_delete_category(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    try:
        cid = int(params["category_id"])
    except (KeyError, TypeError, ValueError):
        return False
    return confirmar_mudanca(ctx, lambda s: s.find_channel(cid) is None)


def _move_channel(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_CHANNELS, what="mover canal")
    try:
        cid = int(params["channel_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError("channel_id invalido", user_message="Preciso do ID do canal.") from exc
    channel = ctx.snapshot.find_channel(cid)
    if channel is None:
        raise NotFound(f"canal {cid}", user_message="Esse canal nao existe.")
    if channel.is_category:
        raise ToolError("categoria nao se move assim", user_message="Categorias se reordenam por posicao.")

    has_parent_key = "category_id" in params or "parent_id" in params
    if not has_parent_key and params.get("position") is None:
        raise ToolError("nada para mover", user_message="Me diga para qual categoria ou para qual posicao.")

    parent_id = _resolve_parent(ctx, params) if has_parent_key else channel.parent_id
    position = int(params["position"]) if params.get("position") is not None else None
    moved = ctx.gateway.move_channel(cid, parent_id=parent_id, position=position)
    return {"moved": moved.to_dict()}


def _verify_move_channel(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    snap = ctx.refresh()
    try:
        channel = snap.find_channel(int(params["channel_id"]))
    except (KeyError, TypeError, ValueError):
        return False
    if channel is None:
        return False
    if ("category_id" in params or "parent_id" in params):
        expected = _resolve_parent(ctx, params)
        if channel.parent_id != expected:
            return False
    return True


def _reorder_channels(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_CHANNELS, what="reordenar canais")
    items = params.get("items") or params.get("positions") or []
    if not isinstance(items, list) or not items:
        raise ToolError("lista vazia", user_message="Preciso da lista de canais com as novas posicoes.")
    if len(items) > ctx.limits.max_actions_per_plan:
        raise ToolError(
            "reordenacao grande demais",
            user_message=f"{len(items)} itens de uma vez e demais. Maximo {ctx.limits.max_actions_per_plan}.",
        )
    normalized: list[dict[str, int]] = []
    for item in items:
        if not isinstance(item, dict) or "id" not in item or "position" not in item:
            raise ToolError("item invalido", user_message="Cada item precisa ter 'id' e 'position'.")
        normalized.append({"id": int(item["id"]), "position": int(item["position"])})
    ctx.gateway.bulk_reorder(normalized)
    return {"reordered": len(normalized)}


def _verify_reorder(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    snap = ctx.refresh()
    for item in params.get("items", []):
        channel = snap.find_channel(int(item["id"]))
        if channel is None or channel.position != int(item["position"]):
            return False
    return True


def _set_channel_permissions(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    require_bot_permission(ctx.snapshot, Perm.MANAGE_CHANNELS, what="configurar permissao de canal")
    try:
        cid = int(params["channel_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError("channel_id invalido", user_message="Preciso do ID do canal.") from exc
    channel = ctx.snapshot.find_channel(cid)
    if channel is None:
        raise NotFound(f"canal {cid}", user_message="Esse canal nao existe.")
    try:
        role_id = int(params["role_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError("role_id invalido", user_message="Preciso do ID do cargo.") from exc
    role = ctx.snapshot.find_role(role_id)
    if role is None:
        raise NotFound(f"cargo {role_id}", user_message="Esse cargo nao existe.")

    allow, deny = params.get("allow") or [], params.get("deny") or []
    allow_perms, unknown_allow = split_unknown_permissions(allow)
    deny_perms, unknown_deny = split_unknown_permissions(deny)

    blocked = reject_never_grantable(allow_perms)
    if blocked:
        raise ToolError(
            f"permissoes proibidas: {blocked}",
            user_message=(
                "Nao concedo " + ", ".join(f"**{b}**" for b in blocked)
                + ". Essas permissoes ficam fora do que este agente pode dar."
            ),
        )
    if not allow_perms and not deny_perms:
        raise ToolError("nada para aplicar", user_message="Nao recebi nenhuma permissao valida para aplicar.")

    allow_bits = 0
    for perm, ok in allow_perms.items():
        if ok:
            allow_bits |= int(perm)
    deny_bits = 0
    for perm, ok in deny_perms.items():
        if ok:
            deny_bits |= int(perm)

    merged = list(channel.overwrites)
    merged = [ow for ow in merged if not (ow.target_type == "role" and ow.target_id == role_id)]
    merged.append(Overwrite(target_id=role_id, target_type="role", allow=allow_bits, deny=deny_bits))
    updated = ctx.gateway.set_channel_overwrites(cid, merged)

    return {
        "channel": updated.to_dict(),
        "role": role.name,
        "applied_allow": sorted(p.name.lower() for p, ok in allow_perms.items() if ok),
        "applied_deny": sorted(p.name.lower() for p, ok in deny_perms.items() if ok),
        "ignored_unknown": sorted(set(unknown_allow) | set(unknown_deny)),
    }


def _verify_channel_permissions(ctx: ToolContext, params: dict[str, Any], data: Any) -> bool:
    snap = ctx.refresh()
    try:
        channel = snap.find_channel(int(params["channel_id"]))
        role_id = int(params["role_id"])
    except (KeyError, TypeError, ValueError):
        return False
    if channel is None:
        return False
    return any(ow.target_id == role_id and ow.target_type == "role" for ow in channel.overwrites)


CHANNEL_TOOLS: list[Tool] = [
    Tool(
        name="create_channel",
        description="Cria um canal no servidor atual. Pode colocar dentro de uma categoria existente.",
        parameters={
            "type": "object",
            "properties": {
                "name": _NAME,
                "type": _TYPE,
                "category_id": _CATEGORY_ID,
                "topic": {"type": "string", "description": "Topico/descricao do canal."},
                "nsfw": {"type": "boolean", "description": "Marca o canal como NSFW. Nao vale para voz."},
                "slowmode_delay": {"type": "integer", "description": "Segundos de slowmode, 0 a 21600."},
            },
            "required": ["name"],
        },
        handler=_create_channel,
        requires=Perm.MANAGE_CHANNELS,
        verify=_verify_create_channel,
        label=lambda p: f"criar #{p.get('name', '?')}",
    ),
    Tool(
        name="edit_channel",
        description="Altera nome, topico, NSFW ou slowmode de um canal existente.",
        parameters={
            "type": "object",
            "properties": {
                "channel_id": _CHANNEL_ID,
                "name": _NAME,
                "topic": {"type": "string"},
                "nsfw": {"type": "boolean"},
                "slowmode_delay": {"type": "integer"},
            },
            "required": ["channel_id"],
        },
        handler=_edit_channel,
        requires=Perm.MANAGE_CHANNELS,
        verify=_verify_edit_channel,
        label=lambda p: f"editar #{p.get('channel_id', '?')}",
    ),
    Tool(
        name="delete_channel",
        description="Exclui um canal. Acao destrutiva e irreversivel.",
        parameters={
            "type": "object",
            "properties": {"channel_id": _CHANNEL_ID},
            "required": ["channel_id"],
        },
        handler=_delete_channel,
        destructive=True,
        requires=Perm.MANAGE_CHANNELS,
        verify=_verify_delete_channel,
        label=lambda p: f"excluir #{p.get('channel_id', '?')}",
    ),
    Tool(
        name="create_category",
        description="Cria uma categoria. O nome e normalizado para maiusculas pelo Discord.",
        parameters={
            "type": "object",
            "properties": {"name": _NAME},
            "required": ["name"],
        },
        handler=_create_category,
        requires=Perm.MANAGE_CHANNELS,
        verify=_verify_create_category,
        label=lambda p: f"criar categoria {p.get('name', '?')}",
    ),
    Tool(
        name="edit_category",
        description="Renomeia ou reposiciona uma categoria.",
        parameters={
            "type": "object",
            "properties": {
                "category_id": {"type": "string", "description": "ID da categoria."},
                "name": _NAME,
                "position": {"type": "integer"},
            },
            "required": ["category_id"],
        },
        handler=_edit_category,
        requires=Perm.MANAGE_CHANNELS,
        verify=_verify_edit_category,
        label=lambda p: f"editar categoria {p.get('category_id', '?')}",
    ),
    Tool(
        name="delete_category",
        description=(
            "Exclui uma categoria. Atencao: o Discord NAO apaga os canais dentro dela, "
            "eles ficam sem categoria."
        ),
        parameters={
            "type": "object",
            "properties": {"category_id": {"type": "string", "description": "ID da categoria."}},
            "required": ["category_id"],
        },
        handler=_delete_category,
        destructive=True,
        requires=Perm.MANAGE_CHANNELS,
        verify=_verify_delete_category,
        label=lambda p: f"excluir categoria {p.get('category_id', '?')}",
    ),
    Tool(
        name="move_channel",
        description="Move um canal para outra categoria e/ou muda a posicao dele.",
        parameters={
            "type": "object",
            "properties": {
                "channel_id": _CHANNEL_ID,
                "category_id": _CATEGORY_ID,
                "position": {"type": "integer", "description": "Nova posicao dentro da categoria."},
            },
            "required": ["channel_id"],
        },
        handler=_move_channel,
        requires=Perm.MANAGE_CHANNELS,
        verify=_verify_move_channel,
        label=lambda p: f"mover #{p.get('channel_id', '?')}",
    ),
    Tool(
        name="reorder_channels",
        description="Reposiciona varios canais de uma vez. Use para reorganizar a estrutura.",
        parameters={
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "Lista de {id, position}.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "position": {"type": "integer"},
                        },
                        "required": ["id", "position"],
                    },
                }
            },
            "required": ["items"],
        },
        handler=_reorder_channels,
        requires=Perm.MANAGE_CHANNELS,
        verify=_verify_reorder,
        label=lambda p: f"reordenar {len(p.get('items', []))} canais",
    ),
    Tool(
        name="set_channel_permissions",
        description=(
            "Define sobrescrita de permissao de UM cargo em UM canal. Nao existe "
            "sobrescrita por membro. Nao concede ban/kick/timeout/mention_everyone/administrator."
        ),
        parameters={
            "type": "object",
            "properties": {
                "channel_id": _CHANNEL_ID,
                "role_id": {"type": "string", "description": "ID do cargo."},
                "allow": {
                    "type": "array",
                    "description": "Permissoes a conceder, ex: ['view_channel','send_messages'].",
                    "items": {"type": "string"},
                },
                "deny": {
                    "type": "array",
                    "description": "Permissoes a negar com os mesmos nomes.",
                    "items": {"type": "string"},
                },
            },
            "required": ["channel_id", "role_id"],
        },
        handler=_set_channel_permissions,
        requires=Perm.MANAGE_CHANNELS,
        verify=_verify_channel_permissions,
        label=lambda p: f"permissao de #{p.get('channel_id', '?')} para cargo {p.get('role_id', '?')}",
    ),
]
