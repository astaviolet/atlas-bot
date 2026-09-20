"""Sessao e memoria de contexto, por servidor E por canal.

A memoria permite "agora de permissao de gerenciar canais" referindo-se ao cargo
criado na mensagem anterior. Ela nunca carrega outro guild_id.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import Limits

AFFIRMATIVE = re.compile(r"^\s*(sim|s|confirmo|confirmar|pode|vai|ok|okay|yes|y|claro|manda|fazer|executa|executar)\b", re.I)
NEGATIVE = re.compile(r"^\s*(n[aã]o|n|cancela|cancelar|para|pare|esquece|esqueça|no|nevermind)\b", re.I)


@dataclass
class PendingConfirmation:
    token: str
    calls: list[dict[str, Any]]
    summary: str
    #: Quando o pedido de confirmacao foi feito, no relogio da sessao.
    #: Sem isto nao ha como saber se o "sim" chegou tarde demais.
    created_at: float = 0.0


@dataclass
class Session:
    guild_id: int
    channel_id: int
    limits: Limits
    history: list[dict[str, Any]] = field(default_factory=list)
    pending: PendingConfirmation | None = None
    #: Injetavel para os testes conseguirem avancar o tempo sem dormir.
    clock: Callable[[], float] = time.monotonic
    last_created: dict[str, str] = field(default_factory=dict)

    # -- confirmacao ----------------------------------------------------------
    def confirmacao_vencida(self) -> bool:
        """True se ha um pedido pendente ja fora do prazo.

        Descartar em vez de executar: um plano montado ha dez minutos descreve
        um servidor que pode nao existir mais.
        """
        if self.pending is None:
            return False
        ttl = self.limits.confirmation_ttl_seconds
        if ttl <= 0:
            return False  # 0 ou negativo desliga o prazo
        return (self.clock() - self.pending.created_at) > ttl

    # -- memoria ------------------------------------------------------------
    def remember(self, kind: str, key: str, value: str) -> None:
        """Guarda referencia de objeto criado, ex: role -> "Moderador" -> "8123..."."""
        self.last_created.setdefault(kind, {})  # type: ignore[arg-type]
        if not isinstance(self.last_created.get(kind), dict):
            self.last_created[kind] = {}
        self.last_created[kind][key.lower()] = value

    def recall(self, kind: str, key: str) -> str | None:
        bucket = self.last_created.get(kind)
        if isinstance(bucket, dict):
            return bucket.get(key.lower())
        return None

    # -- historico ----------------------------------------------------------
    def add_user(self, text: str) -> None:
        self.history.append({"role": "user", "parts": [{"text": text}]})
        self._trim()

    def add_assistant_text(self, text: str) -> None:
        self.history.append({"role": "model", "parts": [{"text": text}]})
        self._trim()

    def add_model_calls(self, calls: list[dict[str, Any]]) -> None:
        parts = [
            {
                "function_call": {
                    "id": c.get("id"),
                    "name": c["name"],
                    "args": c.get("args", {}),
                }
            }
            for c in calls
        ]
        self.history.append({"role": "model", "parts": parts})
        self._trim()

    def add_function_results(self, results: list[dict[str, Any]]) -> None:
        parts = [{"function_response": r} for r in results]
        self.history.append({"role": "user", "parts": parts})
        self._trim()

    def _trim(self) -> None:
        max_msgs = self.limits.max_history_messages
        if len(self.history) > max_msgs:
            self.history = self.history[-max_msgs:]

    def clear_history(self) -> None:
        self.history.clear()


class SessionStore:
    """Uma sessao por (guild, canal). Nao existe sessao compartilhada entre servidores."""

    def __init__(self, limits: Limits | None = None) -> None:
        self.limits = limits or Limits()
        self._sessions: dict[tuple[int, int], Session] = {}

    def get(self, guild_id: int, channel_id: int) -> Session:
        key = (int(guild_id), int(channel_id))
        session = self._sessions.get(key)
        if session is None:
            session = Session(guild_id=key[0], channel_id=key[1], limits=self.limits)
            self._sessions[key] = session
        return session

    def drop(self, guild_id: int, channel_id: int) -> None:
        self._sessions.pop((int(guild_id), int(channel_id)), None)

    @property
    def count(self) -> int:
        return len(self._sessions)


def classify_reply(text: str) -> str:
    """Classifica a resposta a um pedido de confirmacao."""
    stripped = (text or "").strip()
    if not stripped:
        return "empty"
    if NEGATIVE.match(stripped):
        return "no"
    if AFFIRMATIVE.match(stripped):
        return "yes"
    return "other"
