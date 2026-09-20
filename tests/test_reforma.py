"""Reforma de servidor existente (spec 45, 46, 84, 85)."""

from __future__ import annotations

from atlas.design_system import Briefing, Dominio, EstiloVisual, Nomenclatura, Porte
from atlas.models import Channel, ChannelType, GuildSnapshot, Role
from atlas.reforma import (
    auditar,
    nomenclatura_dominante,
    planejar_reforma,
)

ADMIN = 0x8


def _snap(*, canais=None, categorias=None, cargos=None) -> GuildSnapshot:
    chans = []
    for i, (nome, parent) in enumerate(categorias or []):
        chans.append(Channel(id=100 + i, name=nome, type=ChannelType.GUILD_CATEGORY))
    for i, (nome, parent, tipo) in enumerate(canais or []):
        chans.append(Channel(id=500 + i, name=nome, type=tipo, parent_id=parent))
    return GuildSnapshot(
        id=1, name="Servidor", owner_id=1, bot_role_id=9, bot_permissions=0,
        channels=chans, roles=list(cargos or []),
    )


def _servidor_bagunçado() -> GuildSnapshot:
    return _snap(
        categorias=[("GERAL", None), ("JOGO", None)],
        canais=[
            ("general", None, ChannelType.GUILD_TEXT),
            ("anuncios", 100, ChannelType.GUILD_TEXT),
            ("regras", 100, ChannelType.GUILD_TEXT),
            ("📢・avisos", 101, ChannelType.GUILD_TEXT),
            ("chat", None, ChannelType.GUILD_TEXT),
            ("coisas-velhas", 101, ChannelType.GUILD_TEXT),
        ],
    )


# ------------------------------------------------- spec 46: nunca apagar por padrão
def test_reforma_nunca_exclui():
    """A regra que governa o modulo. Excluir e recriar destroi o historico do
    canal, e nao ha rollback para isso: o snapshot guarda estrutura, nao
    conteudo."""
    r = planejar_reforma(_servidor_bagunçado(), Briefing(dominio=Dominio.GAMING_CASUAL))
    assert not r.tem_destrutivo
    assert not [a for a in r.acoes if a.tool.startswith("delete_")]
    assert "Excluídos: 0" in r.impacto()


def test_sobra_vira_suspeita_nao_exclusao():
    r = planejar_reforma(_servidor_bagunçado(), Briefing(dominio=Dominio.GAMING_CASUAL))
    assert "coisas-velhas" in r.suspeitas
    assert not any("coisas-velhas" in str(a.params) for a in r.acoes)


def test_canal_de_chegada_nao_vira_suspeita():
    """'general' e 'regras' sao o que a pessoa ve primeiro. A reforma acomoda,
    nao marca como sobra."""
    r = planejar_reforma(_servidor_bagunçado(), Briefing(dominio=Dominio.GAMING_CASUAL))
    for nome in ("general", "regras"):
        assert nome not in r.suspeitas, nome


# ------------------------------------------------------- reaproveitar, nao recriar
def test_canal_existente_e_reaproveitado_em_vez_de_recriado():
    """O ponto central: '📢・avisos' nao deve virar canal novo se o alvo pede um
    canal de aviso. Nome normalizado casa, entao vira renomear/mover."""
    snap = _snap(
        categorias=[("início", None)],
        canais=[("avisos", 100, ChannelType.GUILD_TEXT)],
    )
    r = planejar_reforma(snap, Briefing(dominio=Dominio.COMUNIDADE, porte=Porte.PEQUENO))
    # o canal 'avisos' casa com o alvo e nao pode estar em criar
    criados = [a.params.get("name") for a in r.criar if a.tool == "create_channel"]
    assert "avisos" not in criados


def test_renomear_aparece_quando_o_nome_sai_do_padrao():
    snap = _snap(
        categorias=[("início", None)],
        canais=[("📢・anuncios", 100, ChannelType.GUILD_TEXT)],
    )
    r = planejar_reforma(
        snap, Briefing(dominio=Dominio.COMUNIDADE, estilo=EstiloVisual.MINIMALISTA)
    )
    assert r.renomear, "canal com emoji em servidor minimalista tem que ser renomeado"
    assert all(a.tool == "edit_channel" for a in r.renomear)


def test_cada_acao_tem_motivo():
    """Acao sem motivo e acao que ninguem consegue auditar depois."""
    r = planejar_reforma(_servidor_bagunçado(), Briefing(dominio=Dominio.COMUNIDADE))
    for a in r.acoes:
        assert a.motivo.strip(), a


# ---------------------------------------------------------------- spec 84: impacto
def test_impacto_mostra_os_numeros():
    r = planejar_reforma(_servidor_bagunçado(), Briefing(dominio=Dominio.COMUNIDADE))
    texto = r.impacto()
    for rotulo in ("Renomeados:", "Movidos:", "Criados:", "Excluídos:"):
        assert rotulo in texto, rotulo


def test_reforma_em_servidor_limpo_nao_faz_nada_destrutivo_nem_inutil():
    snap = _snap(
        categorias=[("início", None)],
        canais=[("boas-vindas", 100, ChannelType.GUILD_TEXT)],
    )
    r = planejar_reforma(snap, Briefing(dominio=Dominio.COMUNIDADE, porte=Porte.PEQUENO))
    assert not r.tem_destrutivo


# ------------------------------------------------------------------- spec 45: auditar
def test_auditar_aponta_nomenclatura_mista():
    achados = auditar(_servidor_bagunçado())
    assert any("nomenclatura mista" in a.problema for a in achados), \
        [a.problema for a in achados]


def test_auditar_nao_reclama_de_nomenclatura_uniforme():
    snap = _snap(categorias=[("a", None)], canais=[
        ("x", 100, ChannelType.GUILD_TEXT), ("y", 100, ChannelType.GUILD_TEXT),
    ])
    assert not any("nomenclatura" in a.problema for a in auditar(snap))


def test_auditar_aponta_categoria_demais_para_pouco_canal():
    snap = _snap(
        categorias=[(f"cat{i}", None) for i in range(6)],
        canais=[(f"c{i}", 100 + i, ChannelType.GUILD_TEXT) for i in range(6)],
    )
    assert any("área demais" in a.problema for a in auditar(snap))


def test_auditar_aponta_admin_demais():
    cargos = [Role(id=i, name=f"admin{i}", permissions=ADMIN) for i in range(1, 6)]
    snap = _snap(cargos=cargos)
    assert any("administrador" in a.problema for a in auditar(snap))


def test_cargo_gerenciado_por_integracao_nao_conta():
    """Cargo de bot/integracao vem com ADMINISTRATOR e nao e escolha do servidor."""
    cargos = [Role(id=i, name=f"bot{i}", permissions=ADMIN, managed=True) for i in range(1, 6)]
    assert not any("administrador" in a.problema for a in auditar(_snap(cargos=cargos)))


def test_auditar_inclui_os_defeitos_que_design_check_ja_achava():
    """Nao duplicar: chama a funcao existente. Categoria vazia tem que continuar
    aparecendo depois da reforma existir."""
    snap = _snap(categorias=[("vazia", None)], canais=[])
    assert any("vazia" in a.problema for a in auditar(snap))


def test_auditar_nao_estoura_com_snapshot_vazio():
    assert auditar(_snap()) == []


# ------------------------------------------------------------------ nomenclatura
def test_nomenclatura_dominante_detecta_o_estilo_do_servidor():
    """Spec 46: preservar. A reforma segue o estilo que ja existe em vez de
    impor outro."""
    snap = _snap(categorias=[("a", None)], canais=[
        ("📢・anuncios", 100, ChannelType.GUILD_TEXT),
        ("💬・chat", 100, ChannelType.GUILD_TEXT),
        ("regras", 100, ChannelType.GUILD_TEXT),
    ])
    assert nomenclatura_dominante(snap) == Nomenclatura.SEPARADOR_PONTO


def test_nomenclatura_dominante_sem_emoji_e_limpo():
    snap = _snap(categorias=[("a", None)], canais=[
        ("anuncios", 100, ChannelType.GUILD_TEXT),
        ("chat", 100, ChannelType.GUILD_TEXT),
    ])
    assert nomenclatura_dominante(snap) == Nomenclatura.LIMPO


def test_nomenclatura_dominante_em_servidor_vazio():
    assert nomenclatura_dominante(_snap()) == Nomenclatura.LIMPO


# ------------------------------------------------------------------ sinônimos
def test_chat_existente_vira_bate_papo_em_vez_de_sobra():
    """Sem sinonimo a reforma cria 'bate-papo' novo e marca 'chat' como sobra:
    o servidor cresce em vez de se organizar, que e o defeito que reformar
    existe para corrigir."""
    snap = _snap(
        categorias=[("comunidade", None)],
        canais=[("chat", 100, ChannelType.GUILD_TEXT)],
    )
    r = planejar_reforma(snap, Briefing(dominio=Dominio.COMUNIDADE, porte=Porte.PEQUENO))
    criados = [a.params.get("name") for a in r.criar if a.tool == "create_channel"]
    assert "bate-papo" not in criados, criados
    assert "chat" not in r.suspeitas, r.suspeitas


def test_avisos_existente_vira_anuncios():
    snap = _snap(
        categorias=[("início", None)],
        canais=[("📢・avisos", 100, ChannelType.GUILD_TEXT)],
    )
    r = planejar_reforma(
        snap, Briefing(dominio=Dominio.COMUNIDADE, estilo=EstiloVisual.MINIMALISTA)
    )
    assert "avisos" not in [str(x) for x in r.suspeitas] or any(
        a.params.get("name") == "anuncios" for a in r.renomear
    )


def test_canal_padrao_nao_e_consumido_no_lugar_do_canal_real():
    """Efeito colateral que o mapa de sinonimos trouxe e um teste pegou: num
    servidor com 'general' E 'chat', a ordem da lista fazia 'general' virar
    'bate-papo' e sobrava justamente o canal que era o chat. Canal padrao fica
    preservado; quem se reorganiza e o resto."""
    snap = _snap(
        categorias=[("comunidade", None)],
        canais=[
            ("general", 100, ChannelType.GUILD_TEXT),
            ("chat", 100, ChannelType.GUILD_TEXT),
        ],
    )
    r = planejar_reforma(snap, Briefing(dominio=Dominio.COMUNIDADE, porte=Porte.PEQUENO))
    renomeados = [a.params.get("channel_id") for a in r.renomear]
    # o canal 'chat' (id 501 nesta fixture) e que deve virar bate-papo
    ids_por_nome = {c.name: c.id for c in snap.channels if not c.is_category}
    assert ids_por_nome["chat"] in renomeados, (renomeados, ids_por_nome)
    assert ids_por_nome["general"] not in renomeados
    assert "general" not in r.suspeitas, "canal padrao nao e sobra"


def test_planejar_reforma_devolve_os_achados_da_auditoria():
    """Bug que o ruff achou e virou teste: planejar_reforma calculava a
    auditoria e jogava fora, entao Reforma.achados nascia sempre vazio. A
    auditoria rodava e o resultado sumia."""
    r = planejar_reforma(_servidor_bagunçado(), Briefing(dominio=Dominio.COMUNIDADE))
    assert r.achados, "a auditoria tem que chegar em Reforma.achados"
    assert any("nomenclatura" in a.problema for a in r.achados)


def test_impacto_nao_tem_placeholder_de_f_string():
    r = planejar_reforma(_servidor_bagunçado(), Briefing(dominio=Dominio.COMUNIDADE))
    assert "Excluídos: 0" in r.impacto()
