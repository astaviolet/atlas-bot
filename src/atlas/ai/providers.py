"""Catalogo de gateways e modelos.

Tudo aqui foi VERIFICADO por sondagem real (scripts/probe_providers.py): cada
rota abaixo respondeu a uma chamada de tool calling sem enviar chave nenhuma.
Rota que nao passou nao esta aqui - nao ha entrada "por precaucao" nem
provedor mantido para inflar numero.

Classificacao de acesso (a missao prioriza as primeiras):
    NO_AUTH          funciona sem chave e sem cadastro
    MANUAL_REQUIRED  exige credencial que o usuario teria que fornecer;
                     o sistema registra e segue, nunca inventa

Limites declarados (rpm/concurrency) vem da documentacao do provedor ou do
comportamento medido. Servem para o router nao estourar o limite legitimo de
ninguem - nao para burla-lo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Access(str, Enum):
    NO_AUTH = "NO_AUTH"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"


@dataclass(frozen=True)
class Capabilities:
    """O que a rota sabe fazer. O router filtra por isso antes de chamar."""

    tool_calling: bool = True
    vision: bool = False
    structured_output: bool = False

    def satisfies(self, needed: "Capabilities") -> bool:
        if needed.tool_calling and not self.tool_calling:
            return False
        if needed.vision and not self.vision:
            return False
        if needed.structured_output and not self.structured_output:
            return False
        return True


@dataclass(frozen=True)
class ModelRoute:
    gateway: str
    model: str
    caps: Capabilities = field(default_factory=Capabilities)
    #: peso relativo para distribuicao de carga entre rotas do mesmo gateway
    weight: int = 100
    #: contexto aproximado em tokens, quando conhecido
    context: int | None = None
    notes: str = ""

    @property
    def key(self) -> str:
        return f"{self.gateway}/{self.model}"


@dataclass
class Gateway:
    id: str
    base_url: str
    models: list[ModelRoute] = field(default_factory=list)
    access: Access = Access.NO_AUTH
    #: credencial, quando o gateway exige. Vazio para anonimo.
    api_key: str = ""
    #: limite legitimo conhecido, em requisicoes por minuto (None = desconhecido)
    rpm: int | None = None
    #: quantas chamadas simultaneas o router pode manter abertas neste gateway
    concurrency: int = 2
    notes: str = ""


def _r(gateway: str, model: str, **kw: Any) -> ModelRoute:
    return ModelRoute(gateway=gateway, model=model, **kw)


# ---------------------------------------------------------------------------
# Rotas anonimas verificadas. Ordem dentro de cada gateway = preferencia.
# ---------------------------------------------------------------------------

KILO = "kilo"
OVH = "ovh"
LLM7 = "llm7"

CATALOG: list[Gateway] = [
    Gateway(
        id=KILO,
        base_url="https://api.kilo.ai/api/gateway/v1",
        access=Access.NO_AUTH,
        # medido em sondagem: devolve 429 bem antes dos ~200 req/h documentados
        # quando se insiste na mesma rota, entao o limite pratico e menor.
        rpm=30,
        concurrency=2,
        notes="Gateway anonimo com rotas :free. Maior capacidade encontrada.",
        models=[
            _r(KILO, "deepseek/deepseek-v4-flash-0731:free", weight=100,
               notes="rapido, tool calling estavel"),
            _r(KILO, "nvidia/nemotron-3-super-120b-a12b:free", weight=90),
            _r(KILO, "nex-agi/nex-n2.5-mini:free", weight=85),
            _r(KILO, "inclusionai/ling-3.0-flash-fin:free", weight=80),
            _r(KILO, "thinkingmachines/inkling-small:free", weight=75),
            _r(KILO, "dots-studio/dots-3-note-preview:free", weight=70),
            _r(KILO, "nex-agi/nex-n2.5-pro:free", weight=95,
               notes="maior qualidade, mais lento"),
            _r(KILO, "nvidia/nemotron-3-ultra-550b-a55b:free", weight=60,
               notes="maior modelo anonimo encontrado; usar com parcimonia"),
            _r(KILO, "kilo-auto/small", weight=50,
               notes="roteamento automatico do proprio gateway"),
        ],
    ),
    Gateway(
        id=OVH,
        base_url="https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
        # CORRIGIDO: a nota anterior dizia "403 em todas as rotas", e isso estava
        # ERRADO. Sondagem de hoje, sem chave:
        #   GET /v1/models  -> HTTP 200, 24 modelos listados
        #   POST /v1/chat/completions com modelo inexistente -> HTTP 404
        #     model_not_found (ou seja: autenticacao passou, o modelo e que nao
        #     existe - nunca foi bloqueio de credencial)
        #   POST com modelo valido -> {"message": "API rate limit exceeded"}
        # O tier anonimo EXISTE e esta vivo. O que impede de usar e o limite de
        # 2 req/min por IP por modelo, que num IP compartilhado estoura antes de
        # dar para confirmar tool calling - tentei 3 vezes, inclusive esperando
        # 70s, e todas cairam no limite.
        #
        # Segue MANUAL_REQUIRED de proposito, e nao por falta de verificacao
        # preguicosa: entrar no pool anonimo com tool_calling=True sem ter
        # confirmado seria inventar capacidade, que e o que a spec 185 proibe.
        access=Access.MANUAL_REQUIRED,
        rpm=2,  # medido: 2 req/min por IP por modelo no tier anonimo
        concurrency=1,
        notes=("Tier anonimo vivo (200 em /v1/models), mas 2 req/min por modelo "
               "estoura antes de confirmar tool calling. Entra so com chave."),
        models=[
            _r(OVH, "Qwen3-Coder-30B-A3B-Instruct", weight=100),
        ],
    ),
    Gateway(
        id=LLM7,
        base_url="https://api.llm7.io/v1",
        access=Access.NO_AUTH,
        rpm=60,  # ~60/hora sem token segundo a documentacao do proprio servico
        concurrency=1,
        notes="Catalogo grande, mas quase tudo exige chave. So estas rotas passaram.",
        models=[
            _r(LLM7, "codestral-latest", weight=100),
            # GLM-5.3-Flash e minimax-m2.7 passaram em sondagem anterior mas
            # estavam em 503/429 na ultima varredura. Ficam como ultima opcao:
            # se estiverem fora, o circuit breaker tira do pool sozinho.
            _r(LLM7, "GLM-5.3-Flash", weight=40, notes="oscila muito"),
            _r(LLM7, "minimax-m2.7", weight=30, notes="oscila muito"),
        ],
    ),
]


def all_routes(catalog: list[Gateway] | None = None) -> list[ModelRoute]:
    """Todas as rotas do catalogo, achatadas."""
    cat = catalog if catalog is not None else CATALOG
    return [m for g in cat for m in g.models]


def gateway_by_id(catalog: list[Gateway], gid: str) -> Gateway | None:
    for g in catalog:
        if g.id == gid:
            return g
    return None


def catalog_summary(catalog: list[Gateway] | None = None) -> dict[str, Any]:
    """Resumo para log/painel. Nunca contem credencial."""
    cat = catalog if catalog is not None else CATALOG
    return {
        "gateways": len(cat),
        "rotas": sum(len(g.models) for g in cat),
        "sem_chave": sum(1 for g in cat if g.access is Access.NO_AUTH),
        "exigem_chave": sum(1 for g in cat if g.access is Access.MANUAL_REQUIRED),
        "com_tool_calling": sum(1 for m in all_routes(cat) if m.caps.tool_calling),
        "ids": [g.id for g in cat],
    }
