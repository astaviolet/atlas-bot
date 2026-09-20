"""Fabrica central de embeds. Toda resposta do bot sai daqui.

`EmbedSpec` e um objeto neutro (testavel sem Discord); `to_discord_embed()`
converte para discord.Embed. Existe UMA unica saida para o usuario, e ela so
aceita embed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

from .config import Limits


class EmbedKind(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    CONFIRM = "confirm"
    INFO = "info"
    PLAN = "plan"
    RESULT = "result"
    WARNING = "warning"
    HELP = "help"


_STYLE: dict[EmbedKind, tuple[str, int, str]] = {
    # tipo: (emoji do titulo, cor, rotulo de rodape)
    EmbedKind.SUCCESS: ("✅", 0x2ECC71, "concluido"),
    EmbedKind.ERROR: ("❌", 0xE74C3C, "falhou"),
    EmbedKind.CONFIRM: ("❓", 0xF1C40F, "aguardando confirmacao"),
    EmbedKind.INFO: ("ℹ️", 0x3498DB, "informacao"),
    EmbedKind.PLAN: ("📋", 0x9B59B6, "plano"),
    EmbedKind.RESULT: ("📊", 0x1ABC9C, "resultado"),
    EmbedKind.WARNING: ("⚠️", 0xE67E22, "atencao"),
    EmbedKind.HELP: ("🧭", 0x95A5A6, "ajuda"),
}


class EmbedOverflow(ValueError):
    """Texto grande demais para o limite da API do Discord."""


@dataclass
class EmbedField:
    name: str
    value: str
    inline: bool = False


@dataclass
class EmbedSpec:
    kind: EmbedKind
    title: str
    description: str = ""
    fields: list[EmbedField] = field(default_factory=list)
    footer: str = ""
    status: str | None = None

    @property
    def styled_title(self) -> str:
        emoji, _, _ = _STYLE[self.kind]
        return f"{emoji} {self.title}"

    @property
    def color(self) -> int:
        _, color, _ = _STYLE[self.kind]
        return color

    def to_discord_embed(self) -> Any:
        import discord  # import tardio: nao obriga Discord em testes

        embed = discord.Embed(
            title=self.styled_title[:256],
            description=self.description[:4096] or None,
            color=self.color,
        )
        for f in self.fields[:25]:
            embed.add_field(name=f.name[:256], value=f.value[:1024], inline=f.inline)
        embed.set_footer(text=(self.footer or _STYLE[self.kind][2])[:2048])
        return embed

    def to_plain(self) -> str:
        """So para log/teste. NUNCA e o que vai para o Discord."""
        lines = [self.styled_title]
        if self.description:
            lines.append(self.description)
        for f in self.fields:
            lines.append(f"**{f.name}**: {f.value}")
        if self.status:
            lines.append(f"[{self.status}]")
        return "\n".join(lines)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


class EmbedBuilder:
    """Constroi embeds ja respeitando os limites da API."""

    def __init__(self, limits: Limits | None = None) -> None:
        self.limits = limits or Limits()

    def build(
        self,
        kind: EmbedKind,
        title: str,
        description: str = "",
        *,
        fields: Sequence[EmbedField] | None = None,
        footer: str = "",
        status: str | None = None,
    ) -> EmbedSpec:
        safe_fields = [
            EmbedField(
                name=_clip(f.name, 240),
                value=_clip(f.value, self.limits.max_field_value),
                inline=f.inline,
            )
            for f in (fields or [])
        ]
        return EmbedSpec(
            kind=kind,
            title=_clip(title, 240),
            description=_clip(description, self.limits.max_embed_description),
            fields=safe_fields[:25],
            footer=_clip(footer, 1900),
            status=status,
        )

    # -- atalhos semanticos -------------------------------------------------
    def success(self, title: str, description: str = "", **kw: Any) -> EmbedSpec:
        return self.build(EmbedKind.SUCCESS, title, description, **kw)

    def error(self, title: str, description: str = "", **kw: Any) -> EmbedSpec:
        return self.build(EmbedKind.ERROR, title, description, **kw)

    def info(self, title: str, description: str = "", **kw: Any) -> EmbedSpec:
        return self.build(EmbedKind.INFO, title, description, **kw)

    def warning(self, title: str, description: str = "", **kw: Any) -> EmbedSpec:
        return self.build(EmbedKind.WARNING, title, description, **kw)

    def confirm(self, title: str, description: str = "", **kw: Any) -> EmbedSpec:
        return self.build(EmbedKind.CONFIRM, title, description, **kw)

    def plan(self, title: str, steps: Sequence[str], **kw: Any) -> EmbedSpec:
        body = "\n".join(f"`{i + 1}.` {s}" for i, s in enumerate(steps)) or "_plano vazio_"
        return self.build(EmbedKind.PLAN, title, body, **kw)

    def help(self, title: str = "O que eu faco", **kw: Any) -> EmbedSpec:
        return self.build(EmbedKind.HELP, title, **kw)


class PlainTextRejected(RuntimeError):
    """Alguem tentou mandar texto puro. Isso e bug, nao e caminho valido."""


class EmbedOnlySender:
    """Unica saida para o usuario. Recusa texto puro por construcao."""

    def __init__(self, send_embed: Any) -> None:
        self._send_embed = send_embed
        self.sent: list[EmbedSpec] = []

    async def send(self, embed: EmbedSpec) -> None:
        if not isinstance(embed, EmbedSpec):
            raise PlainTextRejected(
                f"tentativa de enviar {type(embed).__name__}; so EmbedSpec e aceito"
            )
        self.sent.append(embed)
        await self._send_embed(embed)

    async def send_many(self, embeds: Sequence[EmbedSpec]) -> None:
        for embed in embeds:
            await self.send(embed)

    @property
    def last(self) -> EmbedSpec | None:
        return self.sent[-1] if self.sent else None
