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


def build_ai_client(settings: Settings, *, allow_missing: bool = False) -> ModelClient:
    """Constroi o cliente de IA a partir da configuracao.

    Com allow_missing=True e sem credencial, devolve um cliente que falha de
    forma controlada em vez de derrubar a subida do bot. Isso deixa o projeto
    inicializavel sem nenhuma chave configurada.
    """
    missing = [n for n in ("AI_API_KEY", "AI_BASE_URL", "AI_MODEL")
               if not getattr(settings, {"AI_API_KEY": "ai_api_key",
                                         "AI_BASE_URL": "ai_base_url",
                                         "AI_MODEL": "ai_model"}[n])]
    if missing:
        if not allow_missing:
            raise ConfigError("Faltam credenciais da camada de IA: " + ", ".join(missing))
        return FailingModelClient(
            "credenciais de IA ausentes: " + ", ".join(missing),
            user_message=(
                "A camada de IA ainda nao esta configurada "
                "(faltam " + ", ".join(missing) + " no .env)."
            ),
        )

    return OpenAICompatibleClient(
        api_key=settings.ai_api_key,
        base_url=settings.ai_base_url,
        model_name=settings.ai_model,
        timeout=settings.limits.ai_timeout_seconds,
        max_retries=settings.limits.ai_max_retries,
    )
