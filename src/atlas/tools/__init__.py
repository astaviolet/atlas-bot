"""Registro completo das ferramentas disponiveis para o agente."""

from __future__ import annotations

from .base import Tool, ToolContext, ToolRegistry
from .channels import CHANNEL_TOOLS
from .read import READ_TOOLS
from .roles import ROLE_TOOLS
from .server import SERVER_TOOLS

__all__ = ["Tool", "ToolContext", "ToolRegistry", "build_registry", "ALL_TOOLS"]

ALL_TOOLS: list[Tool] = [*READ_TOOLS, *CHANNEL_TOOLS, *ROLE_TOOLS, *SERVER_TOOLS]


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_all(ALL_TOOLS)
    return registry
