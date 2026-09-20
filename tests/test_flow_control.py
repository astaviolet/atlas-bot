"""Backpressure (spec 149) e fairness por guild (spec 150)."""

from __future__ import annotations

import pytest
from conftest import final, turn

from atlas.errors import ToolError
from atlas.flow_control import Backpressure, GuildQuota


class _Relogio:
    def __init__(self):
        self.agora = 1000.0

    def __call__(self):
        return self.agora

    def avancar(self, s):
        self.agora += s


# --------------------------------------------------------------- fairness (150)
def test_cota_bloqueia_ao_estourar():
    relogio = _Relogio()
    q = GuildQuota(max_acoes=10, window_seconds=60.0, clock=relogio)

    assert q.admitir(1, 10) == 10
    assert q.estourou(1)
    assert q.restante(1) == 0
    assert q.admitir(1, 5) == 0, "nao pode admitir nada alem do teto"


def test_cota_e_por_guild_nao_global():
    """O ponto da spec 150: o guild 1 cheio nao pode travar o guild 2."""
    relogio = _Relogio()
    q = GuildQuota(max_acoes=5, window_seconds=60.0, clock=relogio)

    q.admitir(1, 5)
    assert q.estourou(1)
    assert q.restante(2) == 5, "outro guild tem que continuar com a cota inteira"
    assert q.admitir(2, 5) == 5


def test_cota_libera_quando_a_janela_passa():
    relogio = _Relogio()
    q = GuildQuota(max_acoes=3, window_seconds=60.0, clock=relogio)
    q.admitir(1, 3)
    assert q.estourou(1)

    relogio.avancar(61.0)
    assert not q.estourou(1), "janela deslizante tem que liberar sozinha"
    assert q.admitir(1, 3) == 3


def test_admitir_parcial_em_vez_de_recusar_tudo():
    """Spec 22: sucesso parcial vale mais que falha total."""
    relogio = _Relogio()
    q = GuildQuota(max_acoes=10, window_seconds=60.0, clock=relogio)
    q.admitir(1, 7)
    assert q.admitir(1, 10) == 3, "cabiam 3, tem que admitir 3 e nao zero"


def test_espera_restante_diz_quanto_falta():
    relogio = _Relogio()
    q = GuildQuota(max_acoes=2, window_seconds=60.0, clock=relogio)
    assert q.espera_restante(1) == 0.0
    q.admitir(1, 2)
    relogio.avancar(10.0)
    assert 49.0 < q.espera_restante(1) <= 50.0


# ----------------------------------------------------------- backpressure (149)
def test_plano_grande_demais_e_recusado():
    b = Backpressure(max_pendentes_por_guild=50, max_guilds_em_voo=2)
    assert b.plano_cabe(50)
    assert not b.plano_cabe(51)


def test_teto_de_guilds_em_voo():
    b = Backpressure(max_pendentes_por_guild=50, max_guilds_em_voo=2)
    assert b.entrar(1) and b.entrar(2)
    assert not b.entrar(3), "o terceiro guild tem que ouvir 'ocupado', nao esperar"
    assert b.em_voo() == 2

    b.sair(1)
    assert b.entrar(3), "saiu um, entra outro"
    assert b.em_voo() == 2


def test_mesmo_guild_entrando_duas_vezes_nao_ocupa_duas_vagas():
    b = Backpressure(max_pendentes_por_guild=50, max_guilds_em_voo=1)
    assert b.entrar(1)
    assert b.entrar(1), "reentrar nao pode consumir vaga nova"
    assert b.em_voo() == 1


# ---------------------------------------------------------------- ponta a ponta
def test_executor_recusa_plano_acima_do_backpressure(harness):
    """Tem que recusar ANTES de executar qualquer acao."""
    from atlas.flow_control import Backpressure

    h = harness([turn(*[("create_channel", {"name": f"c{i}", "type": "text"})
                        for i in range(8)]), final("ok")], seed=False)
    h.agent.executor.flow = Backpressure(max_pendentes_por_guild=5, max_guilds_em_voo=4)
    h.ctx.limits = h.limits  # noqa: B018 - limites do ctx ja estao certos

    out = h.ask("cria 8 canais")

    # Backpressure vem ANTES da confirmacao, e assim que tem que ser: nao se
    # pede "sim" para um plano que nao vai poder rodar.
    assert out.results == [], "nenhuma acao pode ter sido executada"
    assert out.blocked is None, "e recusa por teto, nao pedido de confirmacao"
    textos = " ".join(e.description or "" for e in out.embeds)
    assert "teto" in textos and "por partes" in textos, textos
    assert h.find_channel_id("c0") is None, "nada foi criado"


def test_cota_esgotada_devolve_mensagem_com_prazo(harness):
    from atlas.flow_control import GuildQuota

    relogio = _Relogio()
    h = harness([turn(("create_channel", {"name": "x", "type": "text"})), final("ok")],
                seed=False)
    h.agent.executor.quota = GuildQuota(max_acoes=1, window_seconds=60.0, clock=relogio)
    h.agent.executor.quota.admitir(h.gateway.guild_id, 1)

    with pytest.raises(ToolError) as exc:
        h.agent.executor.prepare(
            [{"name": "create_channel", "args": {"name": "y", "type": "text"}}],
            require_confirmation=False,
        )
    assert "janela" in exc.value.user_message
    assert "Libera em" in exc.value.user_message
