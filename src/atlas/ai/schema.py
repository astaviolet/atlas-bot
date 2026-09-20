"""Conversao das declaracoes de ferramenta para o formato OpenAI de function calling.

As ferramentas ja declaram JSON Schema padrao (minusculo), que e portatil. Aqui
so embrulhamos no envelope que a API OpenAI espera:

    {"type": "function", "function": {"name", "description", "parameters"}}
"""

from __future__ import annotations

from typing import Any

# Campos que o JSON Schema aceita mas que alguns provedores rejeitam dentro de
# "parameters". Sao removidos por seguranca, nao por necessidade nossa.
_STRIP_FROM_PARAMETERS = {"$schema", "$id", "definitions", "$defs", "additionalProperties"}


def _clean_parameters(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: _clean_parameters(value)
            for key, value in node.items()
            if key not in _STRIP_FROM_PARAMETERS
        }
    if isinstance(node, list):
        return [_clean_parameters(item) for item in node]
    return node


def to_openai_tools(declarations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Transforma as declaracoes do registro em tools no formato OpenAI."""
    tools: list[dict[str, Any]] = []
    for declaration in declarations:
        parameters = _clean_parameters(declaration.get("parameters") or {"type": "object", "properties": {}})
        # varios provedores exigem "properties" presente mesmo quando vazio
        parameters.setdefault("type", "object")
        parameters.setdefault("properties", {})
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": declaration["name"],
                    "description": declaration.get("description", ""),
                    "parameters": parameters,
                },
            }
        )
    return tools


def parse_tool_arguments(raw: Any) -> dict[str, Any]:
    """A API OpenAI devolve argumentos como string JSON. Normaliza para dict."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        import json

        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}
