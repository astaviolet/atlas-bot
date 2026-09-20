"""Doubles de teste para a camada de IA.

Permitem exercitar o agente inteiro sem rede e sem credencial. Usados pelos
testes e pelo modo demo. Nao sao importados pelo bot em producao.
"""

from __future__ import annotations

from typing import Any

from ..errors import AIError
from .classificacao import ClasseTarefa
from .base import FunctionCall, ModelTurn


class ScriptedModelClient:
    """Responde com um roteiro fixo, na ordem."""

    def __init__(self, script: list[ModelTurn], *, model_name: str = "scripted") -> None:
        self._script = list(script)
        self.model_name = model_name
        self.prompts: list[list[dict[str, Any]]] = []
        self.system_prompts: list[str] = []
        self.tools_seen: list[list[dict[str, Any]]] = []

    def generate(
        self,
        *,
        system: str,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str | None = None,
        guild_id: int | None = None,
        classe: ClasseTarefa | None = None,
    ) -> ModelTurn:
        self.system_prompts.append(system)
        self.prompts.append([dict(m) for m in history])
        self.tools_seen.append(tools)
        if not self._script:
            return ModelTurn(text="Nao tenho mais nada para fazer.")
        return self._script.pop(0)


class FailingModelClient:
    """Sempre falha. Cobre o caminho de erro da camada de IA."""

    model_name = "failing"

    def __init__(
        self,
        message: str = "gateway indisponivel",
        user_message: str = "A camada de IA falhou agora. Pode tentar de novo daqui a pouco.",
    ) -> None:
        self.message = message
        self.user_message = user_message

    def generate(
        self,
        *,
        system: str,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str | None = None,
        guild_id: int | None = None,
        classe: ClasseTarefa | None = None,
    ) -> ModelTurn:
        raise AIError(self.message, user_message=self.user_message)

    def invalidar_guild(self, guild_id: int) -> None:
        """No-op: fake nao tem cache. Mantem a mesma superficie do Router."""


def call(name: str, args: dict[str, Any] | None = None, *, id: str | None = None) -> FunctionCall:
    """Atalho para montar roteiros de teste."""
    return FunctionCall(name=name, args=dict(args or {}), id=id)


def turn(*calls: FunctionCall) -> ModelTurn:
    return ModelTurn(calls=list(calls))


def final(text: str) -> ModelTurn:
    return ModelTurn(text=text)
