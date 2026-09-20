"""Botoes de confirmacao (spec 73): as sete barreiras."""

from __future__ import annotations

import dataclasses

from atlas.botoes import (
    ACAO_CANCELAR,
    ACAO_CONFIRMAR,
    ler_custom_id,
    mensagem_de_recusa,
    montar_custom_id,
    validar_clique,
)
from atlas.config import Limits
from atlas.session import PendingConfirmation, Session


class _Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _sessao(relogio=None, ttl=300.0, autor=77, token="abc123"):
    limites = dataclasses.replace(Limits(), confirmation_ttl_seconds=ttl)
    s = Session(guild_id=1, channel_id=2, limits=limites,
                clock=relogio or _Relogio())
    s.source_author_id = autor
    s.pending = PendingConfirmation(token=token, calls=[], summary="plano",
                                    created_at=s.clock())
    return s


def _clique(s, *, acao=ACAO_CONFIRMAR, token="abc123", guild=1, user=77):
    return validar_clique(
        custom_id=montar_custom_id(acao, token),
        guild_id_clique=guild,
        user_id_clique=user,
        session=s,
    )


# ------------------------------------------------------------- caminho feliz
def test_clique_valido_confirma():
    v = _clique(_sessao())
    assert v.ok and v.decidir == "confirmar" and v.token == "abc123"


def test_botao_cancelar_tambem_valida():
    v = _clique(_sessao(), acao=ACAO_CANCELAR)
    assert v.ok and v.decidir == "cancelar"


# ---------------------------------------------------- barreira 1: guild (spec 8)
def test_clique_de_outro_guild_e_recusado():
    v = _clique(_sessao(), guild=999)
    assert not v.ok and v.motivo == "guild_diferente"


def test_guild_ausente_e_recusado():
    v = _clique(_sessao(), guild=None)
    assert not v.ok and v.motivo == "guild_diferente"


# ------------------------------------------------------- barreira 2: sessao
def test_sem_confirmacao_pendente():
    s = _sessao()
    s.pending = None
    v = _clique(s)
    assert not v.ok and v.motivo == "sem_confirmacao_pendente"


# --------------------------------------------------- barreira 3: expiracao (19)
def test_confirmacao_expirada_nao_executa():
    """Spec 19: botao antigo nao pode executar operacao nova."""
    relogio = _Relogio()
    s = _sessao(relogio, ttl=300.0)
    relogio.t += 301.0
    v = _clique(s)
    assert not v.ok and v.motivo == "confirmacao_expirada"


def test_dentro_do_prazo_funciona():
    relogio = _Relogio()
    s = _sessao(relogio, ttl=300.0)
    relogio.t += 299.0
    assert _clique(s).ok


# ------------------------------------------------------ barreira 4: acao
def test_acao_desconhecida():
    v = validar_clique(custom_id="atlas_apagar_tudo:abc123", guild_id_clique=1,
                       user_id_clique=77, session=_sessao())
    assert not v.ok and v.motivo == "acao_desconhecida"


def test_custom_id_malformado():
    for ruim in ("", "sem_dois_pontos", "atlas_confirmar:", "atlas_confirmar"):
        v = validar_clique(custom_id=ruim, guild_id_clique=1, user_id_clique=77,
                           session=_sessao())
        assert not v.ok and v.motivo == "acao_desconhecida", ruim


# ------------------------------------------------- barreira 5: token (spec 18)
def test_token_de_outro_plano_e_recusado():
    """O caso central da spec 18: botao que sobrou na tela de uma confirmacao
    anterior nao pode executar a confirmacao seguinte."""
    v = _clique(_sessao(), token="plano_velho")
    assert not v.ok and v.motivo == "token_nao_confere"


# --------------------------------------------------- barreira 6: usuario (7/73)
def test_quem_nao_pediu_nao_confirma():
    v = _clique(_sessao(), user=999)
    assert not v.ok and v.motivo == "usuario_nao_e_o_autor"


def test_usuario_ausente_e_recusado():
    v = _clique(_sessao(), user=None)
    assert not v.ok and v.motivo == "usuario_nao_e_o_autor"


# --------------------------------------------------------------- robustez
def test_validacao_nunca_levanta():
    """Seguranca que levanta excecao vira falha aberta. Tem que devolver recusa."""
    class SessaoQuebrada:
        guild_id = 1
        pending = object()

        def confirmacao_vencida(self):
            raise RuntimeError("boom")

    v = validar_clique(custom_id=montar_custom_id(ACAO_CONFIRMAR, "x"),
                       guild_id_clique=1, user_id_clique=1, session=SessaoQuebrada())
    assert not v.ok and v.motivo == "erro_interno"


def test_mensagem_de_recusa_cobre_todo_motivo():
    """Nenhum motivo pode cair no texto generico: o usuario precisa saber o que
    fazer (spec 74)."""
    motivos = {"guild_diferente", "sem_confirmacao_pendente", "confirmacao_expirada",
               "acao_desconhecida", "token_nao_confere", "usuario_nao_e_o_autor",
               "erro_interno"}
    for m in motivos:
        texto = mensagem_de_recusa(m)
        assert texto and texto != mensagem_de_recusa("__nao_existe__"), m


def test_ler_custom_id_idempotente():
    cid = montar_custom_id(ACAO_CONFIRMAR, "tok123")
    assert ler_custom_id(cid) == (ACAO_CONFIRMAR, "tok123")
    assert ler_custom_id("lixo") == (None, None)
