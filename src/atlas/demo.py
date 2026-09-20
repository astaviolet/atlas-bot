"""Modo demo: roda o agente completo contra um servidor simulado.

Nao precisa de Discord nem de credencial de IA. Usa o mesmo codigo de producao
(Executor, Policy, ActionQueue, ferramentas, embeds), trocando so as duas
pontas externas. Serve para conferir o fluxo inteiro offline.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .agent import build_agent
from .audit import AuditLog
from .config import Limits
from .embeds import EmbedBuilder
from .ai import FunctionCall, ModelTurn, ScriptedModelClient
from .policy import ActionBudget, Policy
from .queue import ActionQueue
from .ratelimit import GuildRateLimiter
from .session import Session
from .testing.fake_gateway import FakeGateway
from .tools import build_registry
from .tools.base import ToolContext


def build_demo_agent(
    gateway: FakeGateway | None = None,
    *,
    script: list[ModelTurn] | None = None,
    limits: Limits | None = None,
    audit: AuditLog | None = None,
) -> tuple[Any, FakeGateway, ScriptedModelClient, AuditLog, Limits]:
    limits = limits or Limits()
    audit = audit or AuditLog(None)
    gateway = gateway or FakeGateway()
    gateway.seed_gamer_layout()

    policy = Policy(
        guild_id=gateway.guild_id,
        budget=ActionBudget(
            max_actions=limits.max_actions_per_plan,
            max_creates=limits.max_creates_per_plan,
            max_deletes=limits.max_deletes_per_plan,
        ),
        destructive_confirm_threshold=limits.destructive_confirm_threshold,
    )
    snapshot = gateway.snapshot()
    ctx = ToolContext(
        guild_id=gateway.guild_id, gateway=gateway, policy=policy, limits=limits, snapshot=snapshot
    )
    registry = build_registry()
    model = ScriptedModelClient(script if script is not None else [])
    limiter = GuildRateLimiter(limits.rate_capacity, limits.rate_refill_per_sec)
    queue = ActionQueue(guild_id=gateway.guild_id, limiter=limiter, audit=audit, dispatch=lambda a: None)

    agent = build_agent(
        ctx=ctx, registry=registry, model=model, builder=EmbedBuilder(limits),
        audit=audit, policy=policy, limits=limits, queue=queue,
    )
    queue.dispatch = agent.executor.dispatch
    return agent, gateway, model, audit, limits


async def run_demo(audit: AuditLog | None = None, *, text: str | None = None) -> int:
    audit = audit or AuditLog(None)
    pedido = text or "Cria uma categoria EVENTOS com um canal de texto avisos."

    script = [
        ModelTurn(calls=[FunctionCall("get_server_info", {})]),
        ModelTurn(calls=[
            FunctionCall("create_category", {"name": "EVENTOS"}),
        ]),
        ModelTurn(calls=[
            FunctionCall("create_channel", {"name": "avisos", "type": "text", "category_id": "__CAT__"}),
        ]),
        ModelTurn(text="Criei a categoria EVENTOS com o canal #avisos dentro."),
    ]

    agent, gateway, model, audit, limits = build_demo_agent(script=script, audit=audit)
    session = Session(guild_id=gateway.guild_id, channel_id=1, limits=limits)

    # o id da categoria so existe depois de criada; o demo resolve na hora
    original_generate = model.generate

    def generate(*, system: str, history: list[dict[str, Any]], tools: list[dict[str, Any]], **extra: Any) -> ModelTurn:
        turn = original_generate(system=system, history=history, tools=tools)
        for call in turn.calls:
            if call.args.get("category_id") == "__CAT__":
                cat = next((c for c in gateway.channels.values() if c.name == "EVENTOS"), None)
                call.args["category_id"] = str(cat.id) if cat else None
        return turn

    model.generate = generate  # type: ignore[method-assign]

    print(f"\nPedido: {pedido}\n")
    outcome = await agent.handle(pedido, session)

    for embed in outcome.embeds:
        print("-" * 60)
        print(embed.to_plain())

    print("-" * 60)
    print("\nEstado final do servidor:")
    for channel in sorted(gateway.channels.values(), key=lambda c: (c.parent_id or 0, c.position)):
        kind = "categoria" if channel.is_category else "canal"
        print(f"  [{kind:<9}] {channel.name}")

    print(f"\nAcoes auditadas: {len(audit.records)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(asyncio.run(run_demo()))
