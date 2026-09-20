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

from .agent import Agent, AgentOutcome, build_agent
from .concurrency import GuildLocks
from .ai import build_ai_client
from .audit import AuditLog
from .config import Settings
from .discord_gateway import DiscordGateway
from .embeds import EmbedBuilder, EmbedOnlySender, EmbedSpec, merge_embeds
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


def mensagem_autorizada(
    *,
    control: discord.abc.GuildChannel | None,
    message_channel: discord.abc.GuildChannel,
    mencionado: bool,
) -> bool:
    """Decide se o bot atende esta mensagem.

    Mencao direta autoriza o canal para aquela mensagem - sem isso a pessoa
    chama o bot em qualquer outro canal e nao acontece nada, sem feedback.
    A seguranca nao depende desta funcao: guild, politica e hierarquia valem
    igual em qualquer canal.
    """
    if mencionado:
        return True
    if control is None:
        return False
    return control.id == message_channel.id


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
        self.guild_locks = GuildLocks()

    # ---------------------------------------------------------------- events
    async def on_ready(self) -> None:
        assert self.user is not None
        log.info("conectado como %s em %d servidor(es)", self.user, len(self.guilds))
        await self._aviso_online()

    async def _aviso_online(self) -> None:
        """Uma linha no canal de controle provando que o processo esta vivo.

        Sem isto nao ha como verificar de fora se o bot hospedado caiu: ele
        ignora mensagens de bots por design (anti-loop), entao nenhum teste
        automatizado consegue dispara-lo. Este aviso e o unico sinal
        observavel de que ele conectou no gateway.

        `on_ready` dispara de novo em cada reconexao, entao o contador segura
        o aviso em um por processo - senao viraria spam a cada queda de rede.
        """
        if self._ready_embeds or not self.settings.startup_notice:
            return

        canal = None
        for guild in self.guilds:
            canal = resolve_control_channel(
                guild, configured_id=self.settings.control_channel_id
            )
            if canal is not None:
                break
        if canal is None:
            log.info("aviso de online pulado: nenhum canal de controle resolvido")
            return

        spec = self.builder.success("", "Online.")
        try:
            await canal.send(view=spec.to_layout_view())
            # A trava vem DEPOIS do envio. Sem canal de controle o bot fica
            # livre para mandar na proxima reconexao - se o canal for criado
            # depois, o aviso ainda aparece.
            self._ready_embeds = 1
            log.info("aviso de online enviado em #%s", canal.name)
        except discord.HTTPException as exc:
            # Nao pode derrubar o bot: o aviso e diagnostico, nao funcionalidade.
            log.warning("nao deu para enviar o aviso de online: %s", exc)

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

        # Mencionou o bot, o canal esta autorizado para ESTA mensagem. Sem isso
        # a pessoa chama o bot e nao acontece nada, sem nenhum feedback - que e
        # exatamente a pior forma de falhar. A seguranca nao mora aqui: guild,
        # politica e permissoes continuam valendo igual em qualquer canal.
        mencionado = self.user is not None and self.user in message.mentions

        control = resolve_control_channel(
            guild,
            configured_id=self.settings.control_channel_id,
            message_channel=message.channel,
        )
        if not mensagem_autorizada(
            control=control, message_channel=message.channel, mencionado=mencionado
        ):
            if control is None:
                log.info(
                    "ignorada: este servidor nao tem canal de controle "
                    "(configure ATLAS_CONTROL_CHANNEL_ID, crie um canal chamado %s "
                    "ou me mencione)",
                    CONTROL_CHANNEL_NAME,
                )
            else:
                log.info(
                    "ignorada: canal de controle e #%s (id %s), mensagem veio de outro "
                    "lugar. Para falar comigo em outro canal, me mencione.",
                    control.name, control.id,
                )
            return
        if mencionado:
            log.info(
                "bot mencionado em #%s: canal autorizado para esta mensagem",
                getattr(message.channel, "name", "?"),
            )

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

        # Sempre UMA mensagem. Se o agente produziu varios embeds (lista de
        # acoes + explicacao), eles sao juntados aqui em vez de virarem duas ou
        # tres mensagens separadas no meio da conversa.
        unico = merge_embeds(outcome.embeds)
        if unico is None:
            log.warning("agente nao produziu embed; respondendo com aviso")
            unico = self.builder.error(
                "Sem resposta", "Fiz o pedido, mas nao tenho o que mostrar. Tenta de novo?"
            )
        log.info("respondendo com 1 mensagem (juntou %d)", len(outcome.embeds))
        try:
            # Passa pelo EmbedOnlySender igual ao caminho classico: a garantia
            # de que so sai EmbedSpec (nunca texto puro) nao pode depender de
            # qual formato de mensagem esta em uso.
            await EmbedOnlySender(self._make_sender_v2(message.channel)).send(unico)
        except discord.HTTPException:
            # Components V2 pode nao estar liberado para este bot ainda. Cai no
            # embed classico em vez de deixar o usuario sem resposta.
            log.exception("Components V2 falhou; usando embed classico")
            await sender.send(unico)

    # ------------------------------------------------------------- processamento
    async def _process(self, guild: discord.Guild, message: discord.Message, text: str, session: Any) -> Any:
        loop = asyncio.get_running_loop()

        # Uma mudanca estrutural por vez no mesmo servidor. Sem isto dois
        # pedidos concorrentes leem snapshots diferentes e escrevem um em cima
        # do outro (spec 64/65). A espera e curta: se nao deu, avisa na hora em
        # vez de deixar a pessoa olhando o bot "pensar" (spec 114).
        with self.guild_locks.tentativa(
            guild.id, self.settings.limits.guild_lock_timeout_seconds
        ) as pegou:
            if not pegou:
                log.warning(
                    "guild %s ja esta sendo alterado; recusando para nao misturar planos",
                    guild.id,
                )
                return AgentOutcome(
                    embeds=[
                        self.builder.warning(
                            "",
                            "Estou no meio de outra mudanca neste servidor. "
                            "Me chama de novo em alguns segundos.",
                        )
                    ],
                    blocked="guild_busy",
                )

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
            # vem de message.channel, ou seja: contexto real do Discord.
            # Nunca de parametro enviado pelo modelo.
            source_channel_id=message.channel.id if message is not None else None,
            source_author_id=message.author.id if message is not None else None,
            source_author_name=(
                getattr(message.author, "display_name", None) or message.author.name
                if message is not None else None
            ),
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

    def _make_sender_v2(self, channel: discord.abc.Messageable) -> Any:
        """Envia em Components V2. Continua sendo UMA mensagem por resposta."""

        async def send(spec: EmbedSpec) -> None:
            await channel.send(view=spec.to_layout_view())

        return send


def run(settings: Settings, audit: AuditLog) -> None:
    if not settings.discord_token:
        raise RuntimeError("DISCORD_TOKEN esta vazio. Preencha o .env antes de iniciar.")
    bot = AtlasBot(settings, audit)
    bot.run(settings.discord_token, log_handler=None)
