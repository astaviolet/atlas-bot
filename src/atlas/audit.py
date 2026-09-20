"""Auditoria em JSONL + filtro que impede segredo de chegar em qualquer log.

O filtro age no nivel do logging (antes do handler), entao vale tanto para o
arquivo quanto para stdout.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
import time
from pathlib import Path
from typing import Any

from .config import SECRET_ENV_NAMES

# Padroes de credencial que a gente mascara mesmo que venham por engano num log.
_REDACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "***REDACTED_GITHUB_PAT***"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "***REDACTED_GITHUB_PAT***"),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"), "***REDACTED_GITLAB_PAT***"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "***REDACTED_OPENAI_KEY***"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"), "***REDACTED_GOOGLE_KEY***"),
    # token de bot do Discord: 3 blocos separados por ponto
    (re.compile(r"\b[A-Za-z0-9_-]{23,26}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{25,}\b"), "***REDACTED_DISCORD_TOKEN***"),
)


class SecretRedactingFilter(logging.Filter):
    """Mascara credenciais em qualquer registro que passar por aqui."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - defensivo
            return True
        redacted = redact(msg)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def redact(text: str) -> str:
    """Aplica todos os padroes de credencial sobre um texto."""
    out = text
    for pattern, repl in _REDACT_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def safe_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Remove chaves que poderiam carregar segredo antes de auditar."""
    if not params:
        return {}
    blocked = {"token", "api_key", "apikey", "secret", "password", "authorization"}
    out: dict[str, Any] = {}
    for key, value in params.items():
        if key.lower() in blocked:
            continue
        if isinstance(value, str) and len(value) > 200:
            value = value[:200] + "...(truncado)"
        out[key] = value
    return out


class AuditLog:
    """Um evento por linha, em JSON. Nunca grava token/key."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._records: list[dict[str, Any]] = []
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        action: str,
        user_id: int | None = None,
        guild_id: int | None = None,
        channel_id: int | None = None,
        params: dict[str, Any] | None = None,
        result: str = "ok",
        error: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "action": action,
            "user_id": user_id,
            "guild_id": guild_id,
            "channel_id": channel_id,
            "params": safe_params(params),
            "result": result,
            "error": redact(error) if error else None,
        }
        if extra:
            entry["extra"] = extra

        # ultima barreira: re-mascara o texto serializado inteiro
        line = redact(json.dumps(entry, ensure_ascii=False, default=str))
        self._records.append(json.loads(line))

        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return self._records[-1]

    @property
    def records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def clear(self) -> None:
        self._records.clear()


def setup_logging(level: int = logging.INFO, audit_path: str | Path | None = None) -> AuditLog:
    """Configura logging padrao com redacao e devolve o AuditLog."""
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    stream.addFilter(SecretRedactingFilter())
    root.addHandler(stream)

    return AuditLog(audit_path)


def assert_no_secret_leaked(text: str) -> None:
    """Usado em teste: falha se uma credencial de ambiente aparecer no texto."""
    import os

    for name in SECRET_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value and value in text:
            raise AssertionError(f"credencial de {name} vazou para o log")
