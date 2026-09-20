"""Cliente para gateway compativel com a API OpenAI.

E o unico modulo do projeto que fala HTTP com um modelo. Serve para OmniRoute e
para qualquer endpoint que exponha `POST /chat/completions` no formato OpenAI:
trocar de provedor e trocar AI_BASE_URL / AI_MODEL, sem tocar no resto do bot.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..errors import AIError
from .base import FunctionCall, ModelTurn
from .schema import parse_tool_arguments, to_openai_tools

log = logging.getLogger(__name__)

DEFAULT_TEMPERATURE = 0.4


class OpenAICompatibleClient:
    """Fala com qualquer endpoint OpenAI-compativel.

    Nao ha logica de provedor aqui: nem lista de modelos fixa, nem nome de modelo
    embutido, nem URL hardcoded. Tudo vem da configuracao.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        timeout: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        if not api_key:
            raise AIError(
                "AI_API_KEY vazia",
                user_message="A chave da camada de IA nao esta configurada no .env.",
            )
        if not base_url:
            raise AIError(
                "AI_BASE_URL vazia",
                user_message="O endereco do gateway de IA nao esta configurado no .env.",
            )
        if not model_name:
            raise AIError(
                "AI_MODEL vazio",
                user_message="Nenhum modelo de IA foi configurado no .env.",
            )

        from openai import OpenAI

        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            max_retries=max_retries,
        )
        self.model_name = model_name

    # ------------------------------------------------------------- historico
    @staticmethod
    def to_messages(history: list[dict[str, Any]], *, system: str) -> list[dict[str, Any]]:
        """Converte o historico neutro da sessao para o formato OpenAI."""
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]

        for entry in history:
            role = entry.get("role", "user")
            parts = entry.get("parts") or []

            texts = [str(p["text"]) for p in parts if isinstance(p, dict) and "text" in p]
            calls = [p["function_call"] for p in parts if isinstance(p, dict) and "function_call" in p]
            responses = [
                p["function_response"] for p in parts if isinstance(p, dict) and "function_response" in p
            ]

            if calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": "\n".join(texts) if texts else None,
                        "tool_calls": [
                            {
                                "id": c.get("id") or f"call_{i}",
                                "type": "function",
                                "function": {
                                    "name": c.get("name", ""),
                                    "arguments": json.dumps(c.get("args") or {}, ensure_ascii=False),
                                },
                            }
                            for i, c in enumerate(calls)
                        ],
                    }
                )
                continue

            if responses:
                # cada resultado vira uma mensagem "tool" propria, casada pelo id
                for r in responses:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": r.get("id") or "call_unknown",
                            "name": r.get("name", ""),
                            "content": json.dumps(r.get("response") or {}, ensure_ascii=False, default=str),
                        }
                    )
                continue

            if texts:
                messages.append(
                    {"role": "assistant" if role == "model" else "user", "content": "\n".join(texts)}
                )

        return messages

    # ---------------------------------------------------------------- chamada
    def generate(
        self,
        *,
        system: str,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn:
        messages = self.to_messages(history, system=system)
        openai_tools = to_openai_tools(tools)

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": DEFAULT_TEMPERATURE,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - fronteira externa
            raise _translate(exc, self.model_name) from exc

        return _parse(response)


def _translate(exc: Exception, model_name: str) -> AIError:
    """Traduz excecao do SDK em AIError com mensagem util para o usuario.

    Import tardio: nao obriga o pacote openai em quem so quer os fakes de teste.
    """
    import openai

    log.error("camada de IA falhou: %s", type(exc).__name__)

    if isinstance(exc, openai.AuthenticationError):
        return AIError(
            "authentication",
            user_message="A chave da camada de IA foi recusada. Confere o AI_API_KEY no .env.",
        )
    if isinstance(exc, openai.RateLimitError):
        return AIError(
            "rate limit",
            user_message="O provedor de IA limitou as requisicoes agora. Tenta de novo em alguns segundos.",
        )
    if isinstance(exc, openai.APITimeoutError):
        return AIError(
            "timeout",
            user_message="A IA demorou demais para responder. Tenta de novo.",
        )
    if isinstance(exc, openai.APIConnectionError):
        return AIError(
            "conexao",
            user_message="Nao consegui falar com o gateway de IA. Confere o AI_BASE_URL.",
        )
    if isinstance(exc, openai.NotFoundError):
        return AIError(
            "modelo nao encontrado",
            user_message=f"O modelo **{model_name}** nao existe nesse gateway. Confere o AI_MODEL.",
        )
    if isinstance(exc, openai.APIStatusError):
        status = getattr(exc, "status_code", "?")
        return AIError(
            f"http {status}",
            user_message=f"O gateway de IA respondeu com erro {status}.",
        )
    return AIError(
        type(exc).__name__,
        user_message="A IA nao respondeu. Tenta de novo em alguns segundos.",
    )


def _parse(response: Any) -> ModelTurn:
    """Extrai texto e tool calls. Tolerante a resposta sem tool_calls."""
    try:
        choice = response.choices[0]
    except (AttributeError, IndexError) as exc:
        raise AIError("resposta sem choices", user_message="O modelo respondeu vazio.") from exc

    message = getattr(choice, "message", None)
    if message is None:
        raise AIError("resposta sem message", user_message="O modelo respondeu vazio.")

    calls: list[FunctionCall] = []
    for tool_call in getattr(message, "tool_calls", None) or []:
        function = getattr(tool_call, "function", None)
        if function is None:
            continue
        calls.append(
            FunctionCall(
                name=str(getattr(function, "name", "") or ""),
                args=parse_tool_arguments(getattr(function, "arguments", None)),
                id=getattr(tool_call, "id", None),
            )
        )

    text = getattr(message, "content", None)
    text = str(text).strip() if text else None

    if not calls and not text:
        raise AIError(
            "resposta sem texto nem tool call",
            user_message="O modelo nao retornou nada utilizavel.",
        )

    return ModelTurn(text=text, calls=calls)
