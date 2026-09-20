"""Ponto de entrada do Atlas.

    python main.py            sobe o bot
    python main.py --health   testa o pool de IA e sai

O bot e o `atlas.minimo`: uma chamada de IA por mensagem, resposta montada em
codigo. O bot antigo (agent + bot + executor + design_system + 25 modulos de
apoio) foi removido porque fazia 4 voltas de IA para criar 1 canal.
"""

from __future__ import annotations

import argparse
import sys

from atlas.audit import setup_logging
from atlas.config import ConfigError, load_settings


def _health() -> int:
    """Sonda o pool de IA gratuito e mostra o que responde agora."""
    import logging

    logging.disable(logging.WARNING)
    from atlas.ai.discovery import probe_rota
    from atlas.ai.providers import CATALOG

    ok = 0
    total = 0
    for gateway in CATALOG:
        for modelo in gateway.models:
            total += 1
            try:
                resultado = probe_rota(gateway, modelo.model)
                estado = resultado.status.value
            except Exception as exc:
                estado = f"ERRO {type(exc).__name__}"
            if estado == "OK":
                ok += 1
            print(f"  {gateway.key}/{modelo.model:34} {estado}")
    print(f"\n  respondendo: {ok}/{total}")
    return 0 if ok else 1


def _check() -> int:
    """Valida configuracao e monta o bot sem conectar.

    O workflow do Actions roda isto antes de subir o bot, para um erro de
    configuracao aparecer em segundos em vez de derrubar a run no meio.
    """
    from atlas.minimo import montar

    settings = load_settings()
    bot = montar(settings=settings)
    print(f"  token: {'ok' if settings.discord_token else 'FALTANDO'}")
    print(f"  ferramentas: {len(bot.registry.names)}")
    print(f"  rotas de IA: {sum(len(g.models) for g in __import__('atlas.ai.providers', fromlist=['CATALOG']).CATALOG)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="atlas")
    parser.add_argument("--health", action="store_true", help="testa o pool de IA e sai")
    parser.add_argument("--check", action="store_true", help="valida a configuracao e sai")
    args = parser.parse_args()

    if args.health:
        return _health()
    if args.check:
        try:
            return _check()
        except ConfigError as exc:
            print(f"configuracao invalida: {exc}", file=sys.stderr)
            return 2

    setup_logging()
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"configuracao invalida: {exc}", file=sys.stderr)
        return 2

    import asyncio

    from atlas.minimo import montar

    bot = montar(settings=settings)
    try:
        asyncio.run(bot.start(settings.discord_token))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
