"""Ponta a ponta REAL: Discord de verdade + IA de verdade + código do bot.

Não é simulação. Conecta com o token real, lê o servidor real, monta o agente
pelo MESMO `_build_agent` do bot e manda um pedido somente-leitura para o pool
de IA real. O que ele provar: o caminho pedido -> IA -> tool call -> Discord
funciona. O que ele NÃO prova: o gatilho de mensagem do Discord (precisa de um
humano mencionar o bot; webhook não serve porque author.bot vem true).
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import discord  # noqa: E402

from atlas.audit import AuditLog  # noqa: E402
from atlas.bot import AtlasBot  # noqa: E402
from atlas.config import load_settings  # noqa: E402

PEDIDO = sys.argv[1] if len(sys.argv) > 1 else "quantos canais e cargos tem esse servidor?"


async def main() -> int:
    settings = load_settings()
    bot = AtlasBot(settings=settings, audit=AuditLog(settings.audit_path))

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    resultado: dict = {}

    @client.event
    async def on_ready() -> None:
        try:
            guild = client.guilds[0]
            print(f"  servidor real: {guild.name} ({guild.id})")
            print(f"  canais: {len(guild.channels)} | cargos: {len(guild.roles)}")
            print(f"  pedido: {PEDIDO!r}")
            print("  ---")

            canal = settings.control_channel_id or guild.channels[0].id
            session = bot.sessions.get(guild.id, canal)
            agent = bot._build_agent(guild, None)
            comeco = time.monotonic()
            # IGUAL AO BOT REAL: o nucleo e sincrono e roda em thread, porque o
            # gateway usa run_coroutine_threadsafe(...).result(). Chamar handle()
            # direto dentro do loop trava: o loop fica bloqueado esperando a
            # corrotina que ele mesmo teria que executar. Foi o que a primeira
            # versao deste script fez - deu "timeout na API do Discord" em toda
            # escrita, e o defeito era do script, nao do produto.
            loop = asyncio.get_running_loop()
            outcome = await loop.run_in_executor(
                None, lambda: asyncio.run(agent.handle(PEDIDO, session))
            )
            durou = time.monotonic() - comeco

            print(f"  estado: {outcome.estado} em {durou:.1f}s")
            print(f"  caminho: {outcome.caminho}")
            print(f"  tools chamadas: {len(outcome.results)}")
            for r in outcome.results:
                print(f"    - {r.action.tool}: ok={r.ok} verificada={r.verified}")
                if not r.ok:
                    print(f"        erro: {str(r.error)[:120]}")
            for e in outcome.embeds:
                # Imprime o que REALMENTE vai ao Discord, nao o EmbedSpec cru:
                # limpar() roda dentro de to_discord_embed(), na ultima etapa.
                # A primeira versao imprimia o cru e mostrou ~140 word joiners
                # que a modelo emitiu - parecia violacao da regra de "sem
                # caracteres estranhos" e nao era.
                d = e.to_discord_embed()
                corpo = d.description or ""
                estranhos = [c for c in corpo if ord(c) in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF)]
                print(f"  embed[{e.kind}] title={d.title!r}: {corpo[:180]!r}")
                print(f"      {len(corpo)} chars | invisiveis: {len(estranhos)}")
            resultado["ok"] = bool(outcome.results) and any(r.ok for r in outcome.results)
        except Exception as exc:  # noqa: BLE001
            print(f"  FALHOU: {type(exc).__name__}: {exc}")
            resultado["ok"] = False
        finally:
            await client.close()

    await client.start(settings.discord_token)
    return 0 if resultado.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
