"""Fixtures do bot minimo.

So o que os testes usam de verdade: um gateway falso com servidor semeado, e os
ids conhecidos desse servidor. O conftest antigo montava Agent, executor, fila,
limiter, relogio falso e policy - tudo do bot que foi removido.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from atlas.config import Limits
from atlas.minimo import politica_para
from atlas.testing.fake_gateway import FakeGateway
from atlas.tools import ToolContext, build_registry

CANAL_ORIGEM = 600000000000000002

# --------------------------------------------------------------- compatibilidade
GUILD_ID = 1546763083005825084
OTHER_GUILD_ID = 999999999999999999


@dataclass
class _Chamada:
    name: str
    args: dict[str, Any]


@dataclass
class _Resultado:
    """O que os testes leem de uma acao executada."""

    action: str
    ok: bool
    data: Any = None
    error: str | None = None
    error_kind: str | None = None
    verified: bool = False
    user_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Desfecho:
    embeds: list[Any] = field(default_factory=list)
    results: list[_Resultado] = field(default_factory=list)
    blocked: list[Any] = field(default_factory=list)
    estado: str = "completed"
    caminho: list[str] = field(default_factory=list)


def turn(*chamadas: Any) -> dict[str, Any]:
    """Um passo do roteiro: as ferramentas que o modelo pediria.

    Aceita `turn(("create_channel", {...}))` ou `turn([(...), (...)])`.
    """
    if len(chamadas) == 1 and isinstance(chamadas[0], list):
        itens = chamadas[0]
    else:
        itens = list(chamadas)
    return {"turn": [_Chamada(n, a) for n, a in itens]}


def final(texto: str) -> dict[str, Any]:
    """O texto final que o modelo devolveria. O bot minimo monta em codigo,
    entao aqui serve so para os testes que verificam a saida."""
    return {"final": texto}



def seeded_ids() -> dict[str, int]:
    """Ids fixos do servidor semeado, para os testes nao chutarem numero."""
    g = FakeGateway(guild_id=GUILD_ID)
    g.seed_gamer_layout()
    ids: dict[str, int] = {}
    for canal in g.channels.values():
        chave = canal.name.replace("-", "_").replace(" ", "_").lower()
        ids[f"ch_{chave}"] = canal.id
        # formato antigo: sufixo com o id do pai, para canais de mesmo nome em
        # categorias diferentes nao colidirem. Mantido porque os testes usam.
        ids[f"ch_{chave}_{canal.parent_id or 0}"] = canal.id
        if canal.is_category:
            ids[f"cat_{chave}"] = canal.id
            ids[f"cat_{chave}_{canal.id}"] = canal.id
    for cargo in g.roles.values():
        chave = cargo.name.replace("-", "_").replace(" ", "_").replace("@", "").lower()
        ids[f"role_{chave}"] = cargo.id
    ids["ch_origem"] = CANAL_ORIGEM
    return ids


IDS = seeded_ids()


class Harness:
    """Servidor falso + ferramentas de verdade, sem IA e sem Discord."""

    def __init__(self, script: list[Any] | None = None, *,
                 gateway: FakeGateway | None = None, seed: bool = True) -> None:
        self._script = list(script or [])
        self.gateway = gateway or FakeGateway(guild_id=GUILD_ID)
        if seed and not self.gateway.channels:
            self.gateway.seed_gamer_layout()
        self.limits = Limits()
        self.policy = politica_para(self.limits, GUILD_ID)
        self.registry = build_registry()
        self.ctx = ToolContext(
            guild_id=GUILD_ID,
            gateway=self.gateway,
            policy=self.policy,
            limits=self.limits,
            snapshot=self.gateway.snapshot(),
        )
        self.ctx.source_channel_id = CANAL_ORIGEM
        from atlas.audit import AuditLog

        self.audit = AuditLog()

    def chamar(self, nome: str, args: dict[str, Any]) -> Any:
        """Executa uma ferramenta de verdade e devolve o resultado."""
        return self.registry.get(nome).handler(self.ctx, args)

    def ask(self, texto: str) -> _Desfecho:
        """Executa o roteiro contra as ferramentas de verdade.

        Nao ha IA aqui: o bot minimo chama a IA de verdade em producao, e nos
        testes o que importa e o que a ferramenta fez no servidor. O roteiro
        substitui a decisao do modelo; a execucao e a mesma do bot.
        """
        desfecho = _Desfecho()
        for passo in self._script:
            if "final" in passo:
                from atlas.embeds import EmbedKind, EmbedSpec

                desfecho.embeds.append(
                    EmbedSpec(kind=EmbedKind.RESULT, title="", description=passo["final"])
                )
                continue
            from atlas.minimo import filtrar_chamadas

            aceitas, bloqueadas = filtrar_chamadas(
                passo.get("turn", []), self.registry, GUILD_ID
            )
            for nome in bloqueadas:
                # nada foi executado, entao nao entra em results: results e o que
                # RODOU. A tentativa fica so em blocked, que e a lista de nomes
                # recusados por nao existirem no registro.
                desfecho.blocked.append(nome)
            for chamada in aceitas:
                desfecho.caminho.append(chamada.name)
                try:
                    dados = self.chamar(chamada.name, chamada.args)
                    desfecho.results.append(
                        _Resultado(action=chamada.name, ok=True, data=dados, verified=True)
                    )
                except Exception as exc:
                    # qualquer erro vira acao bloqueada, nao excecao: e isso que
                    # o bot faz em producao (registra e segue), e e o que os
                    # testes de seguranca verificam.
                    desfecho.blocked.append(chamada.name)
                    desfecho.results.append(
                        _Resultado(
                            action=chamada.name,
                            ok=False,
                            error=str(exc),
                            error_kind=type(exc).__name__,
                            user_message=getattr(exc, "user_message", None),
                        )
                    )
        from atlas.embeds import EmbedKind, EmbedSpec

        if desfecho.blocked and not desfecho.results:
            # recusa total: sobrescreve o texto do modelo, igual ao produto.
            desfecho.estado = "refused"
            desfecho.embeds = [
                EmbedSpec(kind=EmbedKind.ERROR, title="", description="Nao faco isso.")
            ]
        elif not desfecho.embeds:
            desfecho.embeds.append(
                EmbedSpec(kind=EmbedKind.RESULT, title="", description="Feito.")
            )
        return desfecho

    def find_channel_id(self, nome: str) -> int | None:
        for canal in self.gateway.channels.values():
            if canal.name == nome and not canal.is_category:
                return canal.id
        return None

    def find_category_id(self, nome: str) -> int | None:
        for canal in self.gateway.channels.values():
            if canal.is_category and canal.name.strip().upper() == nome.strip().upper():
                return canal.id
        return None

    def find_role_id(self, nome: str) -> int | None:
        for cargo in self.gateway.roles.values():
            if cargo.name == nome:
                return cargo.id
        return None


@pytest.fixture
def harness():
    def _fazer(script: list[Any] | None = None, **kwargs: Any) -> Harness:
        return Harness(script, **kwargs)

    return _fazer


@pytest.fixture
def ids() -> dict[str, int]:
    return IDS
