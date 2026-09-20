#!/usr/bin/env python3
"""Ponto de entrada.

    python main.py            # inicia o bot
    python main.py --check    # valida configuracao e sai
    python main.py --health   # re-testa o pool de IA e imprime o painel
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
    parser.add_argument("--health", action="store_true", help="re-testa o pool de IA e imprime o painel")
    parser.add_argument("--health-pausa", type=float, default=1.0, help="pausa entre sondas do --health")
    parser.add_argument(
        "--pool",
        action="store_true",
        help="lista o pool de IA do catalogo, sem sondar (nao consome cota)",
    )
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

    if args.pool:
        from atlas.ai import build_catalog
        from atlas.ai.providers import catalog_summary

        catalogo = build_catalog(settings)
        resumo = catalog_summary(catalogo)
        print(
            f"[pool] {resumo['gateways']} gateways, {resumo['rotas']} rotas "
            f"({', '.join(resumo['ids']) or 'nenhum'})"
        )
        for gw in catalogo:
            nomes = ", ".join(r.model for r in gw.models)
            acesso = "sem chave" if gw.access is gw.access.NO_AUTH else "exige chave"
            print(f"  - {gw.id:<8} rpm={gw.rpm} conc={gw.concurrency} {acesso} :: {nomes}")
        if resumo["rotas"] == 0:
            print("[pool] NENHUMA rota disponivel - o bot vai falhar na primeira chamada.")
            return 3
        return 0

    if args.health:
        from atlas.ai import build_catalog, formatar_painel
        from atlas.ai.discovery import reavaliar, resumo_probes
        from atlas.ai.providers import catalog_summary
        from atlas.ai.router import Router
        from atlas.ai.stats import PoolStats

        catalogo = build_catalog(settings)
        print(f"re-testando {sum(len(g.models) for g in catalogo)} rotas em "
              f"{len(catalogo)} gateways...\n")

        def mostrar(r):
            marca = "OK " if r.utilizavel else "   "
            lat = f"{r.latency_ms}ms" if r.latency_ms else "-"
            print(f"  {marca} {r.route:<52} {r.status:<16} {lat}")
            if r.detail:
                print(f"        {r.detail}")

        registry, resultados = reavaliar(catalogo, pausa=args.health_pausa, on_result=mostrar)
        router = Router(catalogo, health=registry, stats=PoolStats())
        print()
        print(formatar_painel(router.stats, registry.snapshot(), catalog_summary(catalogo)))
        r = resumo_probes(resultados)
        print(f"\nutilizaveis agora: {r['utilizaveis']}/{r['testadas']}  {r['por_status']}")
        return 0 if r["utilizaveis"] else 3

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

    from atlas.ai import build_catalog

    catalogo = build_catalog(settings)
    rotas = sum(len(g.models) for g in catalogo)
    print(f"[config] pool de IA: {len(catalogo)} gateways, {rotas} rotas "
          f"({', '.join(g.id for g in catalogo)})")
    if settings.usuario_configurou_ia:
        print(f"[config] gateway do .env na frente: {settings.ai_base_url} "
              f"modelos={settings.ai_model}")
    print("[config] chave: " + ("configurada" if settings.ai_api_key else "nao necessaria (pool anonimo)"))

    run_bot(settings, audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
