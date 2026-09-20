"""Recuperacao apos restart (spec 93)."""

from __future__ import annotations

from conftest import final, turn

from atlas.models import Channel, ChannelType, GuildSnapshot, Role
from atlas.recuperacao import (
    RegistrarTarefas,
    avaliar_reinicio,
    relatorio_de_reinicio,
)


def _snap(nomes_canais=(), nomes_cargos=()):
    return GuildSnapshot(
        id=1, name="Ping", owner_id=1, bot_role_id=2, bot_permissions=0,
        channels=[Channel(id=100 + i, name=n,
                          type=ChannelType.GUILD_CATEGORY if n.isupper()
                          else ChannelType.GUILD_TEXT)
                  for i, n in enumerate(nomes_canais)],
        roles=[Role(id=200 + i, name=n) for i, n in enumerate(nomes_cargos)],
    )


# ------------------------------------------------------------------- registro
def test_tarefa_fechada_nao_e_pendente(tmp_path):
    r = RegistrarTarefas(tmp_path)
    r.abrir(1, token="abc", acoes=[{"tool": "create_channel", "params": {"name": "x"}}])
    assert len(r.pendentes(1)) == 1

    r.fechar(1, "abc")
    assert r.pendentes(1) == [], "tarefa concluida nao pode virar candidata a restart"


def test_fechar_outra_tarefa_nao_fecha_esta(tmp_path):
    r = RegistrarTarefas(tmp_path)
    r.abrir(1, token="a", acoes=[])
    r.abrir(1, token="b", acoes=[])
    r.fechar(1, "a")
    assert [p["token"] for p in r.pendentes(1)] == ["b"]


def test_guild_sem_historico_devolve_vazio(tmp_path):
    assert RegistrarTarefas(tmp_path).pendentes(999) == []


# ------------------------------------------------------- o ponto central: nao
# ------------------------------------------------------- reexecutar as cegas
def test_o_que_ja_existe_vira_ja_feito():
    t = {"token": "t", "acoes": [{"tool": "create_channel", "params": {"name": "regras"}}]}
    r = avaliar_reinicio(t, _snap(nomes_canais=["regras"]))
    assert len(r["ja_feito"]) == 1 and r["faltando"] == []
    assert not r["retomavel"], "nada a retomar se ja esta feito"


def test_o_que_nao_existe_vira_faltando():
    t = {"token": "t", "acoes": [{"tool": "create_channel", "params": {"name": "regras"}}]}
    r = avaliar_reinicio(t, _snap())
    assert len(r["faltando"]) == 1
    assert r["retomavel"]


def test_exclusao_que_ainda_existe_nao_aconteceu():
    t = {"token": "t", "acoes": [{"tool": "delete_channel", "params": {"name": "velho"}}]}
    r = avaliar_reinicio(t, _snap(nomes_canais=["velho"]))
    assert len(r["faltando"]) == 1, "o canal ainda esta la: a exclusao nao rodou"


def test_edicao_nunca_e_retomada_automáticamente():
    """Aplicar edit/set duas vezes pode sobrescrever ajuste humano feito no meio.
    Nao da para conferir pelo estado, entao nao se repete."""
    t = {"token": "t", "acoes": [
        {"tool": "edit_role", "params": {"role_id": "5", "color": 0}},
        {"tool": "set_channel_permissions", "params": {"channel_id": "7"}},
        {"tool": "reorder_channels", "params": {}},
    ]}
    r = avaliar_reinicio(t, _snap())
    assert len(r["impossivel"]) == 3
    assert not r["retomavel"], "com acao nao verificavel, nao ha retomada automatica"


def test_cargo_tambem_e_conferido():
    t = {"token": "t", "acoes": [{"tool": "create_role", "params": {"name": "Mod"}}]}
    assert avaliar_reinicio(t, _snap(nomes_cargos=["Mod"]))["ja_feito"]
    assert avaliar_reinicio(t, _snap())["faltando"]


def test_relatorio_diz_que_nao_vai_repetir_as_cegas():
    t = {"token": "t", "acoes": [
        {"tool": "create_channel", "params": {"name": "a"}},
        {"tool": "edit_role", "params": {"role_id": "5"}},
    ]}
    texto = relatorio_de_reinicio(avaliar_reinicio(t, _snap()), "Pinguim")
    assert "interrompida" in texto and "Pinguim" in texto
    assert "às cegas" in texto, texto
    assert "0 ação(ões) já estavam feitas, 1 não foram." in texto
    assert "1 eu não consigo conferir" in texto


# ---------------------------------------------------------------- ponta a ponta
def test_executor_abre_e_fecha_a_tarefa(harness, tmp_path):
    from atlas.recuperacao import RegistrarTarefas

    muitas = [("create_channel", {"name": f"c{i}", "type": "text"}) for i in range(6)]
    h = harness([turn(*muitas), final("ok")], seed=False)
    h.agent.executor.tarefas = RegistrarTarefas(tmp_path)

    # 6 criacoes nao pedem confirmacao (o limiar e 15), entao abre E fecha na
    # mesma chamada. O que da para observar de fora e o arquivo: a intencao foi
    # gravada, e ficou marcada como fechada.
    h.ask("monta 6 canais")
    gid = h.gateway.guild_id
    registro = h.agent.executor.tarefas._caminho(gid)  # noqa: SLF001
    assert registro.exists(), "a intencao tinha que ter sido gravada"
    assert h.agent.executor.tarefas.pendentes(gid) == [], \
        "terminou: nao pode sobrar tarefa aberta"

    import json
    linhas = [json.loads(x) for x in
              registro.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert linhas[0]["fechada"] is True
    assert len(linhas[0]["acoes"]) == 6, "as 6 acoes da intencao tem que estar la"


def test_tarefa_interrompida_de_verdade_e_detectada(harness, tmp_path):
    """O cenario da spec 93: o processo caiu no meio, entao ninguem fechou."""
    from atlas.recuperacao import RegistrarTarefas, avaliar_reinicio

    h = harness([turn(("create_channel", {"name": "um", "type": "text"})), final("ok")],
                seed=False)
    tarefas = RegistrarTarefas(tmp_path)
    tarefas.abrir(h.gateway.guild_id, token="caiu", acoes=[
        {"tool": "create_channel", "params": {"name": "um"}},
        {"tool": "create_channel", "params": {"name": "dois"}},
    ])

    pendentes = tarefas.pendentes(h.gateway.guild_id)
    assert len(pendentes) == 1, "ninguem fechou: tem que aparecer como pendente"

    # "um" foi criado antes da queda; "dois" nao
    h.ask("cria um")
    aval = avaliar_reinicio(pendentes[0], h.gateway.snapshot())
    assert len(aval["ja_feito"]) == 1 and len(aval["faltando"]) == 1
    assert aval["retomavel"]


def test_tarefa_pequena_nao_abre_registro(harness, tmp_path):
    from atlas.recuperacao import RegistrarTarefas

    h = harness([turn(("create_channel", {"name": "um", "type": "text"})), final("ok")],
                seed=False)
    h.agent.executor.tarefas = RegistrarTarefas(tmp_path)
    h.ask("cria um canal")
    assert h.agent.executor.tarefas.pendentes(h.gateway.guild_id) == []
