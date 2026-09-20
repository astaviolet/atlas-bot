"""Bot minimo: voce fala, ele responde. Voce pede, ele faz.

POR QUE ISTO EXISTE
-------------------
O bot anterior fazia 4 chamadas de IA para criar 1 canal: classificar, planejar,
executar, conferir. Cada chamada num provedor gratuito custa de 1 a 8 segundos.
O resultado era uma espera de 20 segundos para uma acao de 1.

Aqui sao **uma chamada por mensagem, sempre**. A resposta e montada em codigo a
partir do que a ferramenta devolveu, entao nao existe segunda volta para
"escrever bonitinho". As ferramentas ja trazem `user_message`; juntar isso e
instantaneo.

O QUE CONTINUA DE PE (porque seguranca nao e atraso)
---------------------------------------------------
- guild_id vem do contexto real do Discord, nunca do modelo
- o canal de controle nao pode ser apagado (bloqueio na ferramenta)
- as 21 ferramentas sao o unico repertorio: nao existe ban, kick, DM
- 3 ou mais exclusoes pedem confirmacao antes
- uma mensagem por resposta, curta, sem mencao real de @everyone

O QUE SAIU: design_system, reforma, alertas, perguntas, autofix, recuperacao,
queue, fairness, backpressure, snapshot em disco, observability, botoes,
progresso, conferencia, flow_control, estados, dependencias.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

import discord

from .ai.providers import CATALOG
from .ai.router import Router
from .audit import AuditLog
from .embeds import EmbedKind, EmbedSpec
from .errors import ToolError
from .policy import Policy
from .texto import limpar
from .tools import ToolContext, build_registry

log = logging.getLogger("atlas")

#: Nome e marca do canal de controle. Moram aqui, e nao num modulo de apoio,
#: porque tools/channels.py importa isto para se recusar a apagar o canal.
#: Quando moravam em bot.py, apagar bot.py quebrou a guarda em silencio: ela
#: passou a levantar ModuleNotFoundError em vez de barrar. So o teste pegou.
CONTROL_CHANNEL_NAME = "atlas-config"
CONTROL_TOPIC_MARK = "[atlas-control]"
CONTROL_NAME = CONTROL_CHANNEL_NAME
CONTROL_MARK = CONTROL_TOPIC_MARK
MAX_TEXTO = 400

SYSTEM = """Voce configura a estrutura de servidores do Discord: categorias, canais, cargos, permissoes e ordem.

Regras:
- Responda curto, uma ou duas frases, em portugues do Brasil.
- Use as ferramentas para ler e mudar o servidor. Nao invente numero nem nome de canal.
- Se o pedido nao for sobre o servidor, responda em uma frase e nao chame ferramenta.
- Nunca chame ferramenta para cumprimentar."""

# 3 ou mais exclusoes: pede confirmacao antes. Mesmo numero do bot anterior.
LIMIAR_DESTRUICAO = 3

_CONFIRMA = re.compile(r"^(sim|confirmo|confirmar|pode|vai|ok|ok\.|pode ir|manda)\b", re.I)


@dataclass
class Pendencia:
    """Pedido destrutivo esperando o 'sim' do usuario."""

    calls: list[dict[str, Any]]
    resumo: str
    channel_id: int


@dataclass
class Estado:
    pendente: Pendencia | None = None
    chamadas: int = 0


def _limits_do(settings: Any) -> Any:
    if settings is not None and getattr(settings, "limits", None) is not None:
        return settings.limits
    from .config import Limits

    return Limits()


def politica_para(limits: Any, guild_id: int = 0) -> Policy:
    """Policy com budget real. Fica aqui para bot e teste usarem a mesma coisa."""
    from .policy import ActionBudget

    return Policy(
        guild_id=guild_id,
        budget=ActionBudget(
            max_actions=limits.max_actions_per_plan,
            max_creates=limits.max_creates_per_plan,
            max_deletes=limits.max_deletes_per_plan,
        ),
        destructive_confirm_threshold=limits.destructive_confirm_threshold,
    )


def filtrar_chamadas(
    calls: list[Any], registry: Any, guild_id: int
) -> tuple[list[Any], list[str]]:
    """Barreira de seguranca antes de executar qualquer coisa.

    Duas coisas, e as duas em codigo porque prompt nao e barreira:

    1. So existem as 21 ferramentas registradas. O modelo pode pedir
       `ban_member` a vontade: nao esta no registro, nao executa. E assim que o
       bot fica incapaz de moderar membro, e nao por pedir educadamente.

    2. `guild_id` vindo do modelo e descartado. A guild real vem do contexto do
       Discord; se o modelo (ou uma injecao no texto) mandar outra, ignora.
    """
    aceitas: list[Any] = []
    bloqueadas: list[str] = []
    for call in calls:
        nome = getattr(call, "name", "")
        if nome not in registry.names:
            bloqueadas.append(nome or "sem_nome")
            continue
        args = dict(getattr(call, "args", {}) or {})
        for chave in ("guild_id", "guild", "server_id"):
            args.pop(chave, None)
        call.args = args
        aceitas.append(call)
    return aceitas, bloqueadas


class AtlasMinimo(discord.Client):
    """Um cliente, uma chamada de IA por mensagem, resposta em codigo."""

    def __init__(self, *, settings: Any = None, audit: AuditLog | None = None) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.settings = settings
        self.audit = audit or AuditLog()
        self.registry = build_registry()
        self.router = Router(list(CATALOG), backoff_seconds=0.0)
        self.estados: dict[int, Estado] = {}
        self.limites: dict[int, list[float]] = {}

    # ------------------------------------------------------------------ ciclo
    async def on_ready(self) -> None:
        log.info("conectado como %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        bot_id = self.user.id if self.user else 0
        if not message.mentions or not any(m.id == bot_id for m in message.mentions):
            return
        if not await self._autorizado(message):
            return
        if not self._dentro_do_limite(message.guild.id):
            await self._responder(message, "Devagar. Manda de novo em alguns segundos.")
            return

        texto = self._limpar_mencao(message.content)
        if not texto:
            return
        estado = self.estados.setdefault(message.guild.id, Estado())

        try:
            if estado.pendente and estado.pendente.channel_id == message.channel.id:
                if _CONFIRMA.match(texto.strip()):
                    await self._executar(message, estado, estado.pendente.calls, "")
                    estado.pendente = None
                    return
                estado.pendente = None

            await self._tratar(message, estado, texto)
        except Exception:
            log.exception("falha ao tratar mensagem")
            try:
                await self._responder(message, "Deu erro aqui. Manda de novo.")
            except Exception:
                log.exception("nem a resposta de erro saiu")

    # ------------------------------------------------------------ autorizacao
    async def _autorizado(self, message: discord.Message) -> bool:
        """So responde no canal de controle.

        guild_id e canal vem do contexto real do Discord, nunca do modelo nem do
        usuario. Sem isso qualquer um em qualquer servidor mandaria no bot.
        """
        canal = message.channel
        if isinstance(canal, discord.CategoryChannel):
            return False
        nome = (canal.name or "").strip().lower()
        topico = getattr(canal, "topic", None) or ""
        return nome == CONTROL_NAME or CONTROL_MARK in topico

    def _limpar_mencao(self, texto: str) -> str:
        bot_id = self.user.id if self.user else 0
        return re.sub(rf"<@!?{bot_id}>", "", texto).strip()

    def _dentro_do_limite(self, guild_id: int) -> bool:
        """12 mensagens por minuto por servidor. Simples e suficiente."""
        agora = asyncio.get_running_loop().time()
        fila = [t for t in self.limites.get(guild_id, []) if agora - t < 60]
        fila.append(agora)
        self.limites[guild_id] = fila
        return len(fila) <= 12

    # ------------------------------------------------------------ tratamento
    async def _tratar(self, message: discord.Message, estado: Estado, texto: str) -> None:
        guild = message.guild
        assert guild is not None
        loop = asyncio.get_running_loop()
        gateway = self._gateway(guild, loop)
        lim = _limits_do(self.settings)
        ctx = ToolContext(
            guild_id=guild.id,
            gateway=gateway,
            policy=politica_para(lim, guild.id),
            limits=lim,
            snapshot=gateway.snapshot(),
        )
        ctx.source_channel_id = message.channel.id

        tools = self.registry.declarations()
        try:
            resposta = await asyncio.to_thread(
                self.router.generate,
                system=SYSTEM,
                history=[{"role": "user", "content": texto[:1500]}],
                tools=tools,
                guild_id=guild.id,
            )
        except Exception as exc:
            log.warning("ia falhou: %s", exc)
            await self._responder(message, "A IA nao respondeu agora. Tenta de novo.")
            return

        estado.chamadas += 1
        calls, bloqueadas = filtrar_chamadas(resposta.calls, self.registry, guild.id)
        if bloqueadas:
            self.audit.record(
                action="minimo.ferramenta_inexistente",
                guild_id=guild.id,
                channel_id=message.channel.id,
                extra={"pedidas": bloqueadas},
            )

        if not calls:
            if bloqueadas:
                # o modelo pediu coisa que nao existe no registro. Nao repassar o
                # texto dele: quem pediu tem que ouvir "nao faco isso".
                await self._responder(message, "Nao faco isso.")
                return
            texto_final = limpar(resposta.text or "", limite=MAX_TEXTO)
            await self._responder(message, texto_final or "Nao entendi o que voce quer no servidor.")
            return

        destrutivas = sum(self.registry.get(c.name).count_destructive(c.args) for c in calls)
        if destrutivas >= LIMIAR_DESTRUICAO:
            resumo = f"Isso vai excluir {destrutivas} itens e nao da para desfazer. Confirma?"
            estado.pendente = Pendencia(calls, resumo, message.channel.id)
            await self._responder(message, resumo)
            return

        await self._executar(message, estado, calls, resposta.text or "", ctx=ctx)

    async def _executar(
        self,
        message: discord.Message,
        estado: Estado,
        calls: list[Any],
        fallback: str,
        *,
        ctx: ToolContext | None = None,
    ) -> None:
        guild = message.guild
        assert guild is not None
        if ctx is None:
            loop = asyncio.get_running_loop()
            gateway = self._gateway(guild, loop)
            lim = _limits_do(self.settings)
            ctx = ToolContext(
                guild_id=guild.id,
                gateway=gateway,
                policy=politica_para(lim, guild.id),
                limits=lim,
                snapshot=gateway.snapshot(),
            )
            ctx.source_channel_id = message.channel.id

        feitas: list[str] = []
        erros: list[str] = []
        for call in calls[:20]:
            try:
                await asyncio.to_thread(self.registry.get(call.name).handler, ctx, call.args)
                feitas.append(f"{call.name} ok")
            except ToolError as exc:
                erros.append(exc.user_message or str(exc))
                log.warning("tool %s falhou: %s", call.name, exc)
            except Exception:
                erros.append("Deu erro ao executar.")
                log.exception("tool %s quebrou", call.name)

        self.audit.record(
            action="minimo.exec",
            guild_id=guild.id,
            channel_id=message.channel.id,
            result="ok" if not erros else "partial",
            extra={"tools": [c.name for c in calls], "ok": len(feitas), "erros": len(erros)},
        )

        partes: list[str] = []
        if feitas:
            partes.append(self._resumo_das_acoes(calls[:20]))
        if erros:
            partes.append(erros[0])
        texto = limpar(" ".join(p for p in partes if p), limite=MAX_TEXTO)
        if not texto:
            texto = limpar(fallback, limite=MAX_TEXTO) or "Feito."
        await self._responder(message, texto)

    @staticmethod
    def _resumo_das_acoes(calls: list[Any]) -> str:
        """Resposta em codigo, nao em IA: zero latencia e nao inventa nada."""
        verbos = {
            "create_channel": "Criei o canal",
            "delete_channel": "Apaguei o canal",
            "edit_channel": "Editei o canal",
            "create_category": "Criei a categoria",
            "delete_category": "Apaguei a categoria",
            "edit_category": "Editei a categoria",
            "create_role": "Criei o cargo",
            "edit_role": "Editei o cargo",
            "delete_role": "Apaguei o cargo",
            "move_channel": "Movi o canal",
            "move_role": "Movi o cargo",
            "reorder_channels": "Reordenei os canais",
            "edit_server": "Atualizei o servidor",
            "set_channel_permissions": "Atualizei as permissoes do canal",
            "set_role_permissions": "Atualizei as permissoes do cargo",
            "get_server_info": "Li o servidor",
            "get_channels": "Li os canais",
            "get_categories": "Li as categorias",
            "get_channel": "Li o canal",
            "get_roles": "Li os cargos",
            "get_role": "Li o cargo",
        }
        nomes: list[str] = []
        for call in calls:
            nome = call.args.get("name") or call.args.get("channel_id") or ""
            nomes.append(f"{verbos.get(call.name, call.name)} {nome}".strip())
        if len(nomes) == 1:
            return f"{nomes[0]}."
        return f"Feito: {len(nomes)} acoes."

    # ----------------------------------------------------------------- saida
    async def _responder(self, message: discord.Message, texto: str) -> None:
        """Uma mensagem, um embed, sem titulo e sem rodape. Sempre.

        Mencao de @everyone sai armada: pode aparecer no texto, nunca dispara.
        """
        texto = limpar(texto or "", limite=MAX_TEXTO) or "Feito."
        for palavra in ("@everyone", "@here"):
            texto = texto.replace(palavra, palavra.replace("@", ""))
        embed = EmbedSpec(kind=EmbedKind.RESULT, title="", description=texto).to_discord_embed()
        try:
            await message.reply(embed=embed, mention_author=False)
        except Exception:
            log.exception("nao consegui responder")

    # --------------------------------------------------------------- apoios
    def _gateway(self, guild: discord.Guild, loop: asyncio.AbstractEventLoop) -> Any:
        from .discord_gateway import DiscordGateway

        return DiscordGateway(guild, loop)



def montar(settings: Any = None, audit: AuditLog | None = None) -> AtlasMinimo:
    return AtlasMinimo(settings=settings, audit=audit)
