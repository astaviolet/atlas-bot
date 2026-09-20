"""Perguntas objetivas (spec 130, 132)."""

from __future__ import annotations

from atlas.perguntas import formatar_perguntas, perguntas_necessarias


# ------------------------------------------------- a regra: perguntar é exceção
def test_pedido_comum_nao_gera_pergunta():
    """O resultado normal tem que ser lista vazia. Se este modulo perguntar com
    frequencia, quem esta errado e ele, nao o usuario."""
    assert perguntas_necessarias() == []
    assert perguntas_necessarias(suspeitas=[], destruicoes_pendentes=0) == []


def test_tema_ausente_nao_gera_pergunta():
    """'Monta um servidor' sem tema cai em COMUNIDADE, que e reversivel.
    Perguntar ali seria travar o pedido por algo que da para corrigir depois -
    e o usuario ja disse para nao perguntar o que da para decidir sozinho."""
    assert perguntas_necessarias(suspeitas=None) == []


# --------------------------------------------- o unico caso: decisao irreversivel
def test_sobra_de_reforma_gera_pergunta():
    p = perguntas_necessarias(suspeitas=["coisas-velhas", "antigo"])
    assert len(p) == 1
    assert "coisas-velhas" in p[0].texto and "antigo" in p[0].texto
    assert "apago" in p[0].texto


def test_pergunta_tem_motivo_e_caminho_padrao():
    """Pergunta sem motivo e preguica. E tem que haver um caminho se o usuario
    nao responder - senao o pedido fica travado para sempre."""
    p = perguntas_necessarias(suspeitas=["x"])[0]
    assert p.motivo.strip()
    assert "não é excluído" in p.padrao_se_sem_resposta or "deixar" in p.padrao_se_sem_resposta


def test_lista_grande_vira_amostra():
    """Vinte nomes numa pergunta nao e pergunta objetiva, e despejo."""
    p = perguntas_necessarias(suspeitas=[f"canal-{i}" for i in range(20)])[0]
    assert p.texto.count("canal-") <= 8
    assert "mais 12" in p.texto
    assert "20" in p.texto, "a contagem total tem que aparecer"


def test_exclusao_em_quantidade_pede_confirmacao():
    p = perguntas_necessarias(destruicoes_pendentes=5)
    assert len(p) == 1 and "5 exclusões" in p[0].texto
    assert p[0].padrao_se_sem_resposta == "não executar"


def test_duas_perguntas_viram_uma_mensagem_curta():
    """O usuario pediu uma mensagem so e o minimo que resolve."""
    ps = perguntas_necessarias(suspeitas=["a"], destruicoes_pendentes=3)
    texto = formatar_perguntas(ps)
    assert texto.count("\n") == 1
    assert texto.startswith("- ")


def test_formatar_vazio():
    assert formatar_perguntas([]) == ""
    assert formatar_perguntas(perguntas_necessarias()) == ""


def test_sobra_vazia_ou_em_branco_nao_gera_nada():
    assert perguntas_necessarias(suspeitas=[]) == []
    assert perguntas_necessarias(suspeitas=["", "   "]) == []


# ---------------------------------------------------------- ligacao com a reforma
def test_reforma_alimenta_as_perguntas():
    """As suspeitas da reforma tem que chegar na pergunta - senao os dois modulos
    existem sem se falar, que foi o erro das Fases 21 e 25."""
    from atlas.design_system import Briefing, Dominio
    from atlas.models import Channel, ChannelType, GuildSnapshot
    from atlas.reforma import planejar_reforma

    chans = [
        Channel(id=100, name="início", type=ChannelType.GUILD_CATEGORY),
        Channel(id=500, name="tralha-antiga", type=ChannelType.GUILD_TEXT, parent_id=100),
    ]
    snap = GuildSnapshot(id=1, name="S", owner_id=1, bot_role_id=9,
                         bot_permissions=0, channels=chans)
    reforma = planejar_reforma(snap, Briefing(dominio=Dominio.COMUNIDADE))
    ps = perguntas_necessarias(suspeitas=reforma.suspeitas)
    if reforma.suspeitas:
        assert ps and "tralha-antiga" in ps[0].texto
    else:
        assert ps == []


def test_pergunta_chega_na_proposta_de_reforma():
    """Ligacao: sem isto perguntas.py existiria sem estar conectado, que foi o
    erro das Fases 21 e 25."""
    from atlas.design import proposta_de_reforma
    from atlas.models import Channel, ChannelType, GuildSnapshot

    chans = [
        Channel(id=100, name="início", type=ChannelType.GUILD_CATEGORY),
        Channel(id=500, name="tralha-antiga", type=ChannelType.GUILD_TEXT, parent_id=100),
    ]
    snap = GuildSnapshot(id=1, name="S", owner_id=1, bot_role_id=9,
                         bot_permissions=0, channels=chans)
    t = proposta_de_reforma("arruma esse servidor", snap, n_membros=40)
    # sem condicional frouxa: ou a pergunta esta la, ou o teste tem que falhar
    assert "PERGUNTE AO USUÁRIO ANTES DE EXECUTAR" in t, t[-200:]
    assert "Deixo como estão ou apago?" in t


def test_pedido_sem_sobra_nao_gera_pergunta_na_proposta():
    from atlas.design import proposta_de_reforma
    from atlas.models import Channel, ChannelType, GuildSnapshot

    chans = [
        Channel(id=100, name="início", type=ChannelType.GUILD_CATEGORY),
        Channel(id=500, name="boas-vindas", type=ChannelType.GUILD_TEXT, parent_id=100),
        Channel(id=501, name="regras", type=ChannelType.GUILD_TEXT, parent_id=100),
    ]
    snap = GuildSnapshot(id=1, name="S", owner_id=1, bot_role_id=9,
                         bot_permissions=0, channels=chans)
    t = proposta_de_reforma("arruma esse servidor", snap, n_membros=40)
    assert "PERGUNTE AO USUÁRIO" not in t
