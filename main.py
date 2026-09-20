#!/usr/bin/env python3
"""Ponto de entrada.

    python main.py            # inicia o bot (precisa de .env preenchido)
    python main.py --check    # valida configuracao e sai
    python main.py --demo     # roda o agente contra um servidor simulado
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from atlas.audit import setup_logging
from atlas.bot import run as run_bot
from atlas.config import ConfigError, load_settings
from atlas.demo import run_demo


def main() -> int:
    parser = argparse.ArgumentParser(description="Atlas - agente de configuracao de servidores Discord")
    parser.add_argument("--check", action="store_true", help="valida configuracao e sai")
    parser.add_argument("--demo", action="store_true", help="roda contra servidor simulado, sem Discord")
    parser.add_argument("--demo-text", default=None, help="pedido a usar no modo demo")
    args = parser.parse_args()

    if args.demo:
        audit = setup_logging(audit_path=None)
        return asyncio.run(run_demo(audit, text=args.demo_text))

    try:
        settings = load_settings(require_secrets=False)
    except ConfigError as exc:
        print(f"[config] {exc}", file=sys.stderr)
        return 2

    audit = setup_logging(audit_path=settings.audit_path)

    if args.check:
        faltando = settings.missing()
        print("[config] variaveis:")
        for key, value in settings.describe().items():
            print(f"  {key}: {value}")
        if faltando:
            print("\n[config] FALTANDO: " + ", ".join(faltando))
            print("           Preencha no .env (veja .env.example). Nenhuma credencial e inventada aqui.")
            return 2
        print("\n[config] OK - tudo preenchido")
        return 0

    if not settings.discord_token:
        raise RuntimeError("Falta DISCORD_TOKEN no .env - sem ele o bot nao conecta.")

    if settings.missing():
        # Nao e fatal: o bot sobe e responde com um embed explicando que a
        # camada de IA esta sem credencial. Nenhuma chave e inventada aqui.
        print(
            "[config] AVISO: camada de IA sem credencial ("
            + ", ".join(settings.missing())
            + "). O bot vai conectar, mas pedidos vao receber um embed de erro."
        )

    run_bot(settings, audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
