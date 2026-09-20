"""Configuracao central. Carrega de variaveis de ambiente, nunca de literal no codigo.

A camada de IA e acessada por AI_BASE_URL / AI_API_KEY / AI_MODEL. O bot nao
conhece provedor nenhum: fala com um endpoint compativel com a API OpenAI e
quem decide o provedor e o gateway na outra ponta.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Configuracao invalida ou ausente."""


# Nomes de variaveis de ambiente consideradas sensiveis. Usado pelo filtro de
# redacao. A protecao real contra credencial em log e por formato (regex em
# audit.py), que cobre chave Google, OpenAI, PATs e token de bot independente
# do nome da variavel.
SECRET_ENV_NAMES: frozenset[str] = frozenset(
    {
        "DISCORD_TOKEN",
        "AI_API_KEY",
    }
)


# ---------------------------------------------------------------- sem chave
# O provedor padrao e publico e anonimo: nao pede conta, nao pede cartao e nao
# pede chave. As tres variaveis continuam existindo e continuam vencendo - se
# um dia voce quiser apontar para outro gateway, e so preencher o .env.
#
# AI_MODEL e uma lista em ordem de preferencia. Endpoints gratuitos devolvem
# 429/503 com frequencia, entao o cliente tenta o proximo da lista. Os tres
# abaixo foram verificados como anonimos E com suporte a tool calling.
DEFAULT_AI_BASE_URL = "https://api.llm7.io/v1"
DEFAULT_AI_MODEL = "codestral-latest,GLM-5.3-Flash,minimax-m2.7"

# O SDK openai se recusa a instanciar com api_key vazia, mas este endpoint
# ignora o header de autorizacao (verificado: aceita "Bearer nao-tem-chave" e
# responde normalmente). Entao isto e um marcador de protocolo exigido pelo
# cliente, NAO uma credencial. Nao da acesso a nada e nao e segredo.
NO_KEY_PLACEHOLDER = "sem-chave"


@dataclass(frozen=True)
class Limits:
    """Limites centralizados. Sao a unica fonte de verdade para cotas."""

    # cota por plano (uma solicitacao do usuario)
    max_actions_per_plan: int = 60
    max_creates_per_plan: int = 40
    max_deletes_per_plan: int = 25

    # a partir de quantas acoes destrutivas exige confirmacao explicita
    destructive_confirm_threshold: int = 3

    # balde de tokens por guild
    rate_capacity: int = 12
    rate_refill_per_sec: float = 2.0

    # laco do agente
    max_turns: int = 25

    # texto
    max_embed_description: int = 1800
    max_field_value: int = 900
    max_history_messages: int = 24

    # estrutura
    # max_name_len e max_topic_len seguem a doc oficial do Discord
    # (nome 1-100, topico 0-1024). max_server_description e um teto local
    # conservador: o numero exato da API nao esta documentado na pagina do
    # recurso Guild, entao ele fica aqui para ser ajustado se necessario.
    max_channels_per_category: int = 50
    max_name_len: int = 100
    max_topic_len: int = 1024
    max_server_name_len: int = 100
    max_server_description: int = 120
    max_role_count: int = 250

    # camada de IA
    ai_timeout_seconds: float = 60.0
    ai_max_retries: int = 2


@dataclass(frozen=True)
class Settings:
    discord_token: str
    ai_api_key: str = ""
    ai_base_url: str = DEFAULT_AI_BASE_URL
    ai_model: str = DEFAULT_AI_MODEL
    control_channel_id: int | None = None
    audit_path: str = "logs/audit.jsonl"
    limits: Limits = field(default_factory=Limits)

    def describe(self) -> dict[str, Any]:
        """Versao segura para log. Nunca contem segredo."""
        return {
            "discord_token": "***" if self.discord_token else "(vazio)",
            "ai_api_key": "***" if self.ai_api_key else "(nao necessaria - endpoint anonimo)",
            "ai_base_url": self.ai_base_url or "(vazio)",
            "ai_model": self.ai_model or "(vazio)",
            "control_channel_id": self.control_channel_id,
            "audit_path": self.audit_path,
        }

    def missing(self) -> list[str]:
        """O que ainda falta preencher no .env.

        So o token do Discord e obrigatorio. A camada de IA tem padrao anonimo,
        entao AI_BASE_URL / AI_MODEL vazios nao sao "faltando": caem no padrao.
        """
        faltando = []
        if not self.discord_token:
            faltando.append("DISCORD_TOKEN")
        return faltando

    def with_limits(self, **changes: Any) -> "Settings":
        return replace(self, limits=replace(self.limits, **changes))


def _opt_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} precisa ser um inteiro, veio {raw!r}") from exc


def _normalize_base_url(raw: str) -> str:
    """Garante que a URL base nao termine com barra (o cliente OpenAI nao quer)."""
    url = raw.strip()
    return url.rstrip("/") if url else ""


def load_settings(
    env_file: str | os.PathLike[str] | None = ".env",
    *,
    require_secrets: bool = True,
) -> Settings:
    """Le .env + ambiente. Com require_secrets=False aceita valores vazios."""
    if env_file is not None:
        load_dotenv(env_file, override=False)

    settings = Settings(
        discord_token=os.getenv("DISCORD_TOKEN", "").strip(),
        ai_api_key=os.getenv("AI_API_KEY", "").strip(),
        ai_base_url=_normalize_base_url(os.getenv("AI_BASE_URL", "")) or DEFAULT_AI_BASE_URL,
        ai_model=os.getenv("AI_MODEL", "").strip() or DEFAULT_AI_MODEL,
        control_channel_id=_opt_int("ATLAS_CONTROL_CHANNEL_ID"),
        audit_path=os.getenv("ATLAS_AUDIT_PATH", "logs/audit.jsonl").strip() or "logs/audit.jsonl",
    )

    if require_secrets:
        faltando = settings.missing()
        if faltando:
            raise ConfigError(
                "Faltam credenciais no .env: " + ", ".join(faltando) + "."
            )

    return settings


def ensure_parent_dir(path: str | os.PathLike[str]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
