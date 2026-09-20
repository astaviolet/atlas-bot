"""Cliente Discord. Faz tres coisas e nada alem:

1. Decide se a mensagem veio do canal de controle autorizado.
2. Monta o contexto vinculado ao guild real da interacao.
3. Envia a resposta SEMPRE em embed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord

from .agent import Agent, build_agent
from .ai import build_ai_client
from .audit import AuditLog
from .config import Settings
from .discord_gateway import DiscordGateway
from .embeds import EmbedBuilder, EmbedOnlySender, EmbedSpec
from .policy import ActionBudget, Policy
from .prompts import HELP_TEXT
from .queue import ActionQueue
from .ratelimit import GuildRateLimiter
from .session import SessionStore
from .tools import build_registry
from .tools.base import ToolContext

log = logging.getLogger(__name__)

CONTROL_TOPIC_MARK = "[atlas-control]"
CONTROL_CHANNEL_NAME = "atlas-config"

HELP_WORDS = {"ajuda", "help", "comandos", "o que voce faz", "o que você faz"}


class ControlChannelError(RuntimeError):
    """Nao foi possivel resolver o canal de controle."""


def resolve_control_channel(
    guild: discord.Guild,
    *,
    configured_id: int | None = None,
    message_channel: discord.abc.GuildChannel | None = None,
) -> discord.abc.GuildChannel | None:
    """Acha o canal de controle, sem criar nada (criacao fica em ensure_control_channel)."""
    if configured_id:
        channel = guild.get_channel(configured_id)
        if channel is not None and not isinstance(channel, discord.CategoryChannel):
            return channel

    # canal onde a conversa esta acontecendo so vale se estiver marcado
    if message_channel is not None:
        topic = getattr(message_channel, "topic", None) or ""
        if CONTROL_TOPIC_MARK in topic or message_channel.name == CONTROL_CHANNEL_NAME:
            return message_channel

    for channel in guild.text_channels:
        if channel.name == CONTROL_CHANNEL_NAME or CONTROL_TOPIC_MARK in (channel.topic or ""):
            return channel
    return None


async def ensure_control_channel(
    guild: discord.Guild,
    *,
    member: discord.Member | None,
    configured_id: int | None = None,
) -> discord.abc.GuildChannel:
    """Garante um canal privado. Se precisar criar, cria com acesso restrito."""
    existing = resolve_control_channel(guild, configured_id=configured_id)
    if existing is not None:
        return existing

    me = guild.me
    if me is None or not me.guild_permissions.manage_channels:
        raise ControlChannelError(
            "Nao existe canal de controle e meu cargo nao tem 'Gerenciar canais' para criar um."
        )

    # Sem a intent de membros o `guild.owner` vem None, entao buscamos na API.
    if member is None and guild.owner_id:
        try:
            member = await guild.fetch_member(guild.owner_id)
        except discord.HTTPException:
            member = None

    overwrites: dict[Any, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True),
    }
    if member is not None and member.top_role is not None:
        overwrites[member.top_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    channel = await guild.create_text_channel(
        name=CONTROL_CHANNEL_NAME,
        topic=f"{CONTROL_TOPIC_MARK} Canal de configuracao do Atlas. Somente pessoas autorizadas.",
        overwrites=overwrites,
        reason="Canal de controle do Atlas",
    )
    return channel


class AtlasBot(discord.Client):
    def __init__(self, settings: Settings, audit: AuditLog) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.settings = settings
        self.audit = audit
        self.sessions = SessionStore(settings.limits)
        self.registry = build_registry()
        self.builder = EmbedBuilder(settings.limits)
        # A camada de IA nunca impede a subida: o endpoint padrao e anonimo.
        # ainda nao tiver credencial, em vez de falhar na inicializacao.
        self.model = build_ai_client(settings)
        self.limiter = GuildRateLimiter(
            settings.limits.rate_capacity,
            settings.limits.rate_refill_per_sec,
        )
        self._ready_embeds = 0

    # ---------------------------------------------------------------- events
    async def on_ready(self) -> None:
        assert self.user is not None
        log.info("conectado como %s em %d servidor(es)", self.user, len(self.guilds))

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        guild = message.guild
        if guild is None:
            log.debug("mensagem ignorada: veio de DM")
            return  # DM: o agente nao trabalha fora de servidor
        if not isinstance(message.channel, discord.abc.GuildChannel):
            return

        log.info(
            "mensagem recebida em #%s (id %s) de %s: %r",
            getattr(message.channel, "name", "?"), message.channel.id,
            message.author, (message.content or "")[:80],
        )

        control = resolve_control_channel(
            guild,
            configured_id=self.settings.control_channel_id,
            message_channel=message.channel,
        )
        if control is None:
            log.info(
                "ignorada: este servidor nao tem canal de controle "
                "(configure ATLAS_CONTROL_CHANNEL_ID ou crie um canal chamado %s)",
                CONTROL_CHANNEL_NAME,
            )
            return
        if control.id != message.channel.id:
            log.info(
                "ignorada: canal de controle e #%s (id %s), mensagem veio de outro lugar",
                control.name, control.id,
            )
            return

        text = (message.content or "").strip()
        if not text:
            log.info("ignorada: conteudo vazio")
            return

        sender = EmbedOnlySender(self._make_sender(message.channel))
        session = self.sessions.get(guild.id, message.channel.id)

        if text.lower() in HELP_WORDS:
            await sender.send(self.builder.help("O que eu faco", HELP_TEXT))
            return

        try:
            outcome = await self._process(guild, message, text, session)
        except ControlChannelError as exc:
            log.warning("sem canal de controle: %s", exc)
            await sender.send(self.builder.error("Sem canal de controle", str(exc)))
            return
        except Exception:  # noqa: BLE001 - nunca deixa uma mensagem derrubar o bot
            log.exception("falha ao processar mensagem")
            await sender.send(
                self.builder.error("Algo quebrou aqui", "Deu um erro inesperado do meu lado.")
            )
            return

        log.info("respondendo com %d embed(s)", len(outcome.embeds))
        for embed in outcome.embeds[:3]:
            await sender.send(embed)

    # ------------------------------------------------------------- processamento
    async def _process(self, guild: discord.Guild, message: discord.Message, text: str, session: Any) -> Any:
        loop = asyncio.get_running_loop()
        agent = self._build_agent(guild, message)

        # o nucleo e sincrono; roda em thread para nao travar o loop do gateway
        return await loop.run_in_executor(
            None, lambda: asyncio.run(agent.handle(text, session))
        )

    def _build_agent(self, guild: discord.Guild, message: discord.Message) -> Agent:
        gateway = DiscordGateway(guild, asyncio.get_running_loop())
        snapshot = gateway.snapshot()
        policy = Policy(
            guild_id=guild.id,
            budget=ActionBudget(
                max_actions=self.settings.limits.max_actions_per_plan,
                max_creates=self.settings.limits.max_creates_per_plan,
                max_deletes=self.settings.limits.max_deletes_per_plan,
            ),
            destructive_confirm_threshold=self.settings.limits.destructive_confirm_threshold,
        )
        ctx = ToolContext(
            guild_id=guild.id,
            gateway=gateway,
            policy=policy,
            limits=self.settings.limits,
            snapshot=snapshot,
        )
        queue = ActionQueue(guild_id=guild.id, limiter=self.limiter, audit=self.audit, dispatch=lambda a: None)
        agent = build_agent(
            ctx=ctx,
            registry=self.registry,
            model=self.model,
            builder=self.builder,
            audit=self.audit,
            policy=policy,
            limits=self.settings.limits,
            queue=queue,
        )
        # a fila precisa chamar o executor, que so existe depois de build_agent
        queue.dispatch = agent.executor.dispatch
        return agent

    def _make_sender(self, channel: discord.abc.Messageable) -> Any:
        async def send(embed: EmbedSpec) -> None:
            await channel.send(embed=embed.to_discord_embed())

        return send


def run(settings: Settings, audit: AuditLog) -> None:
    if not settings.discord_token:
        raise RuntimeError("DISCORD_TOKEN esta vazio. Preencha o .env antes de iniciar.")
    bot = AtlasBot(settings, audit)
    bot.run(settings.discord_token, log_handler=None)
