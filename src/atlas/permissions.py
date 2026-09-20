"""Checagens de permissao e hierarquia. Rodam no backend, nao dependem do prompt."""

from __future__ import annotations

from .errors import HierarchyViolation, PermissionError_
from .models import NEVER_GRANTABLE, PERM_ALIASES, PERM_BY_NAME, GuildSnapshot, Perm, Role


def parse_permissions(raw: object) -> dict[Perm, bool]:
    """Converte o que o modelo mandou em {bit: permitir}.

    Aceita lista de nomes ("manage_channels"), dicionario {"manage_channels": true}
    ou alias em portugues. Nomes desconhecidos sao ignorados de forma explicita
    pelo chamador, que recebe as chaves rejeitadas de volta.
    """
    resolved: dict[Perm, bool] = {}

    def add(name: str, allow: bool) -> None:
        key = str(name).strip().lower().replace("-", "_").replace(" ", "_")
        key = PERM_ALIASES.get(key, key)
        perm = PERM_BY_NAME.get(key)
        if perm is not None:
            resolved[perm] = allow

    if isinstance(raw, dict):
        for key, value in raw.items():
            add(str(key), bool(value))
    elif isinstance(raw, (list, tuple, set)):
        for item in raw:
            if isinstance(item, str):
                add(item, True)
            elif isinstance(item, dict) and "name" in item:
                add(str(item["name"]), bool(item.get("allow", True)))
    return resolved


def split_unknown_permissions(raw: object) -> tuple[dict[Perm, bool], list[str]]:
    """Igual a parse_permissions, mas tambem devolve os nomes que nao entendi."""
    known = parse_permissions(raw)
    known_names: set[str] = set()
    items: list[str] = []

    if isinstance(raw, dict):
        for key, value in raw.items():
            items.append(str(key))
            if bool(value):
                known_names.add(str(key))
    elif isinstance(raw, (list, tuple, set)):
        for item in raw:
            if isinstance(item, str):
                items.append(item)
                known_names.add(item)
            elif isinstance(item, dict) and "name" in item:
                items.append(str(item["name"]))
                if bool(item.get("allow", True)):
                    known_names.add(str(item["name"]))

    unknown: list[str] = []
    for name in items:
        key = str(name).strip().lower().replace("-", "_").replace(" ", "_")
        key = PERM_ALIASES.get(key, key)
        if key not in PERM_BY_NAME:
            unknown.append(name)
    return known, unknown


def reject_never_grantable(perms: dict[Perm, bool]) -> list[str]:
    """Devolve os nomes das permissoes que o agente nunca concede."""
    return [p.name.lower() for p, allow in perms.items() if allow and p in NEVER_GRANTABLE]


def has_permission(bitmask: int, perm: Perm) -> bool:
    if bitmask & Perm.ADMINISTRATOR:
        return True
    return bool(bitmask & perm)


def require_bot_permission(snapshot: GuildSnapshot, perm: Perm, *, what: str) -> None:
    if not has_permission(snapshot.bot_permissions, perm):
        raise PermissionError_(
            f"bot sem {perm.name} para {what}",
            user_message=f"Meu cargo nao tem a permissao **{perm.name}**, que e necessaria para {what}.",
        )


def require_role_hierarchy(snapshot: GuildSnapshot, target: Role, *, what: str) -> None:
    """Nunca mexe em cargo no mesmo nivel ou acima do cargo mais alto do bot."""
    bot_role = snapshot.bot_role
    if bot_role is None:  # pragma: no cover - gateway sempre fornece
        raise PermissionError_("nao consegui identificar meu proprio cargo")

    if target.id == snapshot.bot_role_id:
        raise HierarchyViolation(
            f"alvo {target.name} e o proprio cargo do bot",
            user_message="Nao posso alterar o meu proprio cargo.",
        )
    if target.managed:
        raise HierarchyViolation(
            f"cargo {target.name} e gerenciado por integracao",
            user_message=f"**{target.name}** e um cargo de integracao (bot/assinatura). O Discord nao deixa eu mexer nele.",
        )
    if target.id == snapshot.owner_id:  # dono geralmente tem cargo abaixo, mas garantimos
        pass
    if target.position >= bot_role.position:
        raise HierarchyViolation(
            f"cargo {target.name} (pos {target.position}) >= bot (pos {bot_role.position})",
            user_message=(
                f"**{target.name}** esta no mesmo nivel ou acima do meu cargo na hierarquia. "
                f"Para eu {what}, meu cargo precisa ficar acima dele."
            ),
        )


def require_channel_hierarchy(snapshot: GuildSnapshot, channel_name: str, *, what: str) -> None:
    """Canais herdam do cargo; validamos so a permissao base do bot."""
    require_bot_permission(snapshot, Perm.MANAGE_CHANNELS, what=what)
    _ = channel_name  # mantido para simetria de log


def clamp_position(value: int, minimum: int = 0, maximum: int = 500) -> int:
    return max(minimum, min(maximum, int(value)))


def normalize_color(value: object) -> int:
    """Aceita int, '#rrggbb' ou 'rrggbb'."""
    if value is None:
        return 0
    if isinstance(value, bool):
        raise ValueError("cor precisa ser numero ou hexadecimal")
    if isinstance(value, int):
        if not 0 <= value <= 0xFFFFFF:
            raise ValueError("cor fora do intervalo 0..16777215")
        return value
    text = str(value).strip().lstrip("#")
    if not text:
        return 0
    try:
        number = int(text, 16)
    except ValueError as exc:
        raise ValueError(f"cor invalida: {value!r}") from exc
    if not 0 <= number <= 0xFFFFFF:
        raise ValueError("cor fora do intervalo 0..16777215")
    return number
