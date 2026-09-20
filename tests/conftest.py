"""Fixtures. Tudo roda contra o FakeGateway, que imita as restricoes reais do Discord."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from atlas.agent import Agent, build_agent
from atlas.audit import AuditLog
from atlas.config import Limits
from atlas.embeds import EmbedBuilder
from atlas.ai import FunctionCall, ModelTurn, ScriptedModelClient
from atlas.policy import ActionBudget, Policy
from atlas.queue import ActionQueue
from atlas.ratelimit import GuildRateLimiter
from atlas.session import Session
from atlas.testing.fake_gateway import FakeGateway
from atlas.tools import build_registry
from atlas.tools.base import ToolContext

GUILD_ID = 111111111111111111
OTHER_GUILD_ID = 999999999999999999


class FakeClock:
    """Relogio controlado. Faz o balde de tokens recarregar de forma deterministica."""

    def __init__(self) -> None:
        self.now_seconds = 0.0

    def now(self) -> float:
        return self.now_seconds

    def sleep(self, seconds: float) -> None:
        self.now_seconds += seconds


class Harness:
    """Um agente completo, pronto para receber um pedido."""

    def __init__(
        self,
        script: list[ModelTurn],
        *,
        gateway: FakeGateway | None = None,
        limits: Limits | None = None,
        seed: bool = True,
    ) -> None:
        self.limits = limits or Limits()
        self.audit = AuditLog(None)
        self.gateway = gateway or FakeGateway()
        if seed:
            self.gateway.seed_gamer_layout()

        self.policy = Policy(
            guild_id=self.gateway.guild_id,
            budget=ActionBudget(
                max_actions=self.limits.max_actions_per_plan,
                max_creates=self.limits.max_creates_per_plan,
                max_deletes=self.limits.max_deletes_per_plan,
            ),
            destructive_confirm_threshold=self.limits.destructive_confirm_threshold,
        )
        self.ctx = ToolContext(
            guild_id=self.gateway.guild_id,
            gateway=self.gateway,
            policy=self.policy,
            limits=self.limits,
            snapshot=self.gateway.snapshot(),
        )
        self.registry = build_registry()
        self.model = ScriptedModelClient(script)
        self.clock = FakeClock()
        self.limiter = GuildRateLimiter(
            self.limits.rate_capacity,
            self.limits.rate_refill_per_sec,
            clock=self.clock.now,
            sleeper=self.clock.sleep,
        )
        self.queue = ActionQueue(
            guild_id=self.gateway.guild_id,
            limiter=self.limiter,
            audit=self.audit,
            dispatch=lambda a: None,
        )
        self.agent: Agent = build_agent(
            ctx=self.ctx,
            registry=self.registry,
            model=self.model,
            builder=EmbedBuilder(self.limits),
            audit=self.audit,
            policy=self.policy,
            limits=self.limits,
            queue=self.queue,
        )
        self.queue.dispatch = self.agent.executor.dispatch
        self.session = Session(guild_id=self.gateway.guild_id, channel_id=42, limits=self.limits)

    def ask(self, text: str) -> Any:
        """Roda o agente de forma sincrona."""
        return asyncio.run(self.agent.handle(text, self.session))

    # -- atalhos ------------------------------------------------------------
    @property
    def embeds(self) -> list[Any]:
        return self.session and self._last_outcome.embeds  # type: ignore[attr-defined]

    def find_channel_id(self, name: str) -> int | None:
        for channel in self.gateway.channels.values():
            if channel.name == name and not channel.is_category:
                return channel.id
        return None

    def find_category_id(self, name: str) -> int | None:
        for channel in self.gateway.channels.values():
            if channel.name == name and channel.is_category:
                return channel.id
        return None

    def find_role_id(self, name: str) -> int | None:
        for role in self.gateway.roles.values():
            if role.name == name:
                return role.id
        return None


def seeded_ids() -> dict[str, int]:
    """IDs do layout padrao. Sao deterministas, entao o roteiro pode referencia-los."""
    probe = FakeGateway()
    probe.seed_gamer_layout()
    out: dict[str, int] = {}
    for channel in probe.channels.values():
        if channel.is_category:
            out[f"cat_{channel.name.lower()}"] = channel.id
        else:
            out[f"ch_{channel.name.lower().replace(' ', '_')}_{channel.parent_id}"] = channel.id
    for role in probe.roles.values():
        out[f"role_{role.name.lower().replace(' ', '_').replace('@', '')}"] = role.id
    out["cat_base"] = 600000000000000001
    out["ch_bate_papo"] = 600000000000000002
    return out


IDS = seeded_ids()


def turn(*calls: tuple[str, dict[str, Any]]) -> ModelTurn:
    return ModelTurn(calls=[FunctionCall(name, args) for name, args in calls])


def final(text: str) -> ModelTurn:
    return ModelTurn(text=text)


@pytest.fixture
def harness():
    def factory(script: list[ModelTurn], **kwargs: Any) -> Harness:
        return Harness(script, **kwargs)

    return factory
