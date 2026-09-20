"""Contrato da camada de IA.

O resto do bot conversa SO com `ModelClient`. Nenhum modulo fora de `atlas.ai`
sabe qual provedor existe do outro lado, nem como falar com ele.

    Discord -> Agent -> ModelClient -> (gateway OpenAI-compativel) -> LLM
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class FunctionCall:
    """Uma acao estruturada pedida pelo modelo. Nunca e executada direto."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)
    # identificador do provedor; necessario para casar pedido com resposta
    id: str | None = None


@dataclass
class ModelTurn:
    """O que o modelo devolveu: texto, chamadas de ferramenta, ou os dois."""

    text: str | None = None
    calls: list[FunctionCall] = field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return bool(self.calls)


@runtime_checkable
class ModelClient(Protocol):
    """Porta de saida para o modelo. Implementacoes: OpenAICompatibleClient e fakes."""

    model_name: str

    def generate(
        self,
        *,
        system: str,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str | None = None,
        guild_id: int | None = None,
    ) -> ModelTurn:
        """Pede um turno ao modelo.

        `guild_id` existe por uma razao unica: permitir que a implementacao
        isole cache e metrica por servidor. Ele NUNCA autoriza agir em outro
        servidor - o guild de execucao vem do contexto da interacao, sempre.
        """
        ...


def ensure_call_ids(turn: ModelTurn, *, turn_index: int) -> ModelTurn:
    """Garante que toda chamada tenha id.

    Provedores OpenAI-compativeis devolvem id; provedores mais simples podem nao
    devolver. Sem id nao da para casar a resposta da ferramenta com a chamada, e
    a conversa quebra no segundo turno. Por isso o id e sintetizado aqui, na
    fronteira, e nao espalhado pelo agente.
    """
    fixed: list[FunctionCall] = []
    for i, call in enumerate(turn.calls):
        if call.id:
            fixed.append(call)
        else:
            fixed.append(FunctionCall(name=call.name, args=call.args, id=f"call_t{turn_index}_{i}"))
    return ModelTurn(text=turn.text, calls=fixed)
