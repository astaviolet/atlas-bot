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
                # probe_rota recebe a ModelRoute inteira, nao o nome do modelo
                resultado = probe_rota(gateway, modelo)
                estado = resultado.status.value
            except Exception as exc:
                estado = f"ERRO {type(exc).__name__}: {exc}"
            if estado == "OK":
                ok += 1
            print(f"  {gateway.id}/{modelo.model:34} {estado}")
    print(f"\n  respondendo: {ok}/{total}")
    # Sempre 0. Este passo e informativo: se o pool gratuito estiver esgotado,
    # devolver 1 aqui derruba o job e o bot nao sobe - que foi exatamente o que
    # aconteceu. Pool vazio e motivo para o bot responder "a IA nao respondeu",
    # nao para ele nem existir.
    return 0


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


def _painel() -> int:
    """Resumo curto para o log da run. Nunca derruba o job: e informativo."""
    from atlas.audit import AuditLog

    audit = AuditLog()
    registros = audit.records
    print(f"  acoes auditadas nesta run: {len(registros)}")
    por_acao: dict[str, int] = {}
    for r in registros:
        por_acao[r.get("action", "?")] = por_acao.get(r.get("action", "?"), 0) + 1
    for acao, n in sorted(por_acao.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    {acao:34} {n}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="atlas")
    parser.add_argument("--health", action="store_true", help="testa o pool de IA e sai")
    # --pool e sinonimo de --health: e o nome que o workflow usa
    parser.add_argument("--pool", action="store_true", help="sonda o pool de IA e sai")
    parser.add_argument("--check", action="store_true", help="valida a configuracao e sai")
    parser.add_argument("--painel", action="store_true", help="resumo da auditoria e sai")
    args = parser.parse_args()

    if args.health or args.pool:
        return _health()
    if args.painel:
        return _painel()
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
