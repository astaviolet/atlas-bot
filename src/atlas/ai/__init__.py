"""Camada de IA do Atlas.

Ponto unico por onde o bot chega em um modelo. O resto do projeto importa
`build_ai_client` e o Protocol `ModelClient`, e nao sabe qual provedor existe.

    Discord -> Agent -> ModelClient -> gateway OpenAI-compativel -> LLM
"""

from __future__ import annotations

from typing import Any

from ..config import ConfigError, Settings
from ..errors import AIError
from .base import FunctionCall, ModelClient, ModelTurn, ensure_call_ids
from .fakes import FailingModelClient, ScriptedModelClient
from .openai_client import OpenAICompatibleClient
from .schema import parse_tool_arguments, to_openai_tools

__all__ = [
    "FunctionCall",
    "ModelClient",
    "ModelTurn",
    "OpenAICompatibleClient",
    "ScriptedModelClient",
    "FailingModelClient",
    "build_ai_client",
    "ensure_call_ids",
    "parse_tool_arguments",
    "to_openai_tools",
    "AIError",
]


def build_ai_client(settings: Settings) -> ModelClient:
    """Constroi o cliente de IA a partir da configuracao.

    Nao exige chave: AI_BASE_URL e AI_MODEL tem padrao anonimo em config.py, e
    AI_API_KEY vazia e aceita porque o endpoint publico ignora o header de auth.
    """
    return OpenAICompatibleClient(
        api_key=settings.ai_api_key,
        base_url=settings.ai_base_url,
        model_name=settings.ai_model,
        timeout=settings.limits.ai_timeout_seconds,
        max_retries=settings.limits.ai_max_retries,
    )
