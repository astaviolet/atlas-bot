"""Verificacao ponta a ponta contra o Discord REAL.

Testes com FakeGateway nao exercitam DiscordGateway nem a entrega de evento.
Este script conecta de verdade, roda o agente com o pool de IA real e conta
quantas mensagens chegaram no canal - que e como se descobre coisa do tipo
"o bot mandou duas mensagens" ou "o snapshot quebra em canal com permissao
customizada".

Uso:
    .venv/bin/python scripts/verifica_ponta_a_ponta.py "pedido em linguagem natural"

Requer DISCORD_TOKEN no .env. Cuidado: pedidos que criam coisas criam de
verdade no servidor.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request

import discord
from dotenv import load_dotenv

from atlas.audit import AuditLog
from atlas.bot import AtlasBot
from atlas.config import load_settings
from atlas.embeds import merge_embeds

load_dotenv(".env", override=True)

CANAL_PADRAO = 1551015583712026768  # #atlas-config do servidor Pinguim


def _ultimas_mensagens(canal_id: int, token: str, limite: int = 6) -> list[dict]:
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{canal_id}/messages?limit={limite}",
        headers={"Authorization": f"Bot {token}", "User-Agent": "DiscordBot (atlas, 1.0)"},
    )
    with urllib.request.urlopen(req, timeout=25) as resposta:
        return list(reversed(json.load(resposta)))


async def main() -> int:
    pedido = sys.argv[1] if len(sys.argv) > 1 else "me diz como este servidor esta organizado"
    settings = load_settings(require_secrets=False)
    token = settings.discord_token
    if not token:
        print("DISCORD_TOKEN vazio no .env")
        return 2

    antes = {m["id"] for m in _ultimas_mensagens(CANAL_PADRAO, token, 20)}

    bot = AtlasBot(settings, AuditLog(path=settings.audit_path))
    falha: list[str] = []

    @bot.event
    async def on_ready() -> None:
        try:
            guild = bot.guilds[0]
            canal = guild.get_channel(CANAL_PADRAO)
            if canal is None:
                falha.append(f"canal {CANAL_PADRAO} nao existe neste servidor")
                return
            print(f"servidor: {guild.name} | canal: #{canal.name}")

            autor = type("A", (), {"id": guild.owner_id or 0, "name": "verificacao", "display_name": "verificacao"})()
            mensagem = type("M", (), {"channel": canal, "author": autor})()

            agent = bot._build_agent(guild, mensagem)
            print(f"pedido: {pedido!r}")

            loop = asyncio.get_running_loop()
            session = bot.sessions.get(guild.id, canal.id)
            outcome = await loop.run_in_executor(
                None, lambda: asyncio.run(agent.handle(pedido, session))
            )

            unico = merge_embeds(outcome.embeds)
            print(f"acoes={len(outcome.results)} embeds_produzidos={len(outcome.embeds)}")
            if unico is None:
                falha.append("o agente nao produziu nenhum embed")
                return

            embed = unico.to_discord_embed()
            if embed.title is not None:
                falha.append(f"embed ainda tem titulo: {embed.title!r}")
            if embed.footer.text is not None:
                falha.append(f"embed ainda tem rodape: {embed.footer.text!r}")

            await canal.send(embed=embed)
        except Exception as exc:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            falha.append(f"{type(exc).__name__}: {exc}")
        finally:
            await bot.close()

    await bot.start(token)

    depois = _ultimas_mensagens(CANAL_PADRAO, token, 20)
    novas = [m for m in depois if m["id"] not in antes and m["author"].get("id") != antes]
    do_bot = [m for m in depois if m["id"] not in antes and m.get("embeds")]

    print(f"\nmensagens novas do bot no canal: {len(do_bot)}")
    for m in do_bot:
        for e in m["embeds"]:
            print(f"  titulo={e.get('title')!r} rodape={(e.get('footer') or {}).get('text')!r}")
    if len(do_bot) != 1:
        falha.append(f"esperava 1 mensagem do bot, chegaram {len(do_bot)}")

    if falha:
        print("\nFALHOU:")
        for f in falha:
            print(f"  - {f}")
        return 1
    print("\nOK: uma mensagem, sem titulo, sem rodape")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
