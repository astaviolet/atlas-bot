"""Camada de IA do Atlas.

O resto do bot importa SO o que esta aqui. Fluxo final:

    Discord -> Agent -> Router -> Gateway OpenAI-compativel -> LLM

`Router` e a implementacao padrao de `ModelClient`: escolhe gateway e modelo,
faz failover, respeita o limite legitimo de cada provedor e mantem metrica de
saude. Os fakes (`ScriptedModelClient`, `FailingModelClient`) existem para os
testes nao dependerem de rede.
"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..errors import AIError
from .base import FunctionCall, ModelClient, ModelTurn, ensure_call_ids
from .cache import RequestCache, chave_pedido
from .fakes import FailingModelClient, ScriptedModelClient
from .health import Health, HealthRegistry
from .openai_client import OpenAICompatibleClient
from .providers import CATALOG, Access, Capabilities, Gateway, ModelRoute
from .router import Router
from .schema import parse_tool_arguments, to_openai_tools
from .stats import PoolStats, formatar_painel

__all__ = [
    "Access",
    "Capabilities",
    "FailingModelClient",
    "FunctionCall",
    "Gateway",
    "Health",
    "HealthRegistry",
    "ModelClient",
    "ModelRoute",
    "ModelTurn",
    "OpenAICompatibleClient",
    "PoolStats",
    "RequestCache",
    "Router",
    "ScriptedModelClient",
    "AIError",
    "build_ai_client",
    "build_catalog",
    "chave_pedido",
    "ensure_call_ids",
    "formatar_painel",
    "parse_tool_arguments",
    "to_openai_tools",
]


def build_catalog(settings: Settings) -> list[Gateway]:
    """Catalogo efetivo: o descoberto, mais o que o usuario definir no .env.

    As tres variaveis continuam vencendo. Se AI_BASE_URL estiver preenchida, o
    gateway do usuario entra no pool COM PRIORIDADE (peso maior), e o pool
    anonimo continua atras dele como reserva. Se estiver vazia, so o pool
    anonimo e usado - que e o caso de quem nao quer configurar nada.
    """
    catalog: list[Gateway] = []

    if settings.usuario_configurou_ia:
        modelos = [m.strip() for m in settings.ai_model.split(",") if m.strip()]
        catalog.append(
            Gateway(
                id="configurado",
                base_url=settings.ai_base_url,
                api_key=settings.ai_api_key,
                access=Access.NO_AUTH if not settings.ai_api_key else Access.MANUAL_REQUIRED,
                concurrency=3,
                notes="Definido por AI_BASE_URL/AI_MODEL no .env; tem prioridade no pool.",
                models=[
                    ModelRoute(
                        gateway="configurado",
                        model=m,
                        caps=Capabilities(tool_calling=True),
                        weight=1000,  # na frente do pool anonimo
                    )
                    for m in modelos
                ],
            )
        )

    # Gateway que exige credencial so entra se a credencial existir. Sem isso o
    # router gastaria tentativa em rota que sempre devolve 401/403.
    for g in CATALOG:
        if g.access is Access.MANUAL_REQUIRED and not (g.api_key or settings.ai_api_key):
            continue
        catalog.append(g)
    return catalog


def build_ai_client(settings: Settings, **kw: Any) -> ModelClient:
    """Devolve o cliente de IA padrao: o Router sobre o pool descoberto.

    Nao exige nenhuma credencial. Se o usuario preencher AI_*, aquele gateway
    entra na frente; se nao preencher, o pool anonimo assume sozinho.
    """
    return Router(build_catalog(settings), **kw)
