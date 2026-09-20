"""Fase 8: snapshot logico e rollback (spec 86/87/88)."""

from __future__ import annotations

from conftest import final, turn

from atlas.snapshot_store import SnapshotStore, _sanitizar, plano_de_rollback


class _Acao:
    def __init__(self, tool):
        self.tool = tool


class _Resultado:
    def __init__(self, tool, ok=True, novo_id="123"):
        self.ok = ok
        self.action = _Acao(tool)
        self.data = {"created": {"id": novo_id}} if ok else {}


# ---------------------------------------------------------------- sanitizacao
def test_sanitizar_tira_credencial_em_qualquer_nivel():
    """Spec 94: snapshot nunca guarda segredo, nem se alguem acrescentar campo."""
    sujo = {
        "nome": "ok",
        "token": "ghp_x",
        "aninhado": {"ai_api_key": "sk-x", "discord_token": "t", "canal": "geral"},
        "lista": [{"password": "p", "id": 1}],
    }
    limpo = _sanitizar(sujo)

    texto = repr(limpo)
    assert "ghp_x" not in texto and "sk-x" not in texto
    assert "token" not in limpo and "token" not in limpo["aninhado"]
    assert limpo["aninhado"]["canal"] == "geral", "nao pode apagar o que e util"
    assert limpo["lista"][0] == {"id": 1}


# ------------------------------------------------------------------ ida e volta
def test_salvar_e_ler_com_metadados(tmp_path):
    from atlas.models import Channel, ChannelType, GuildSnapshot, Role

    loja = SnapshotStore(tmp_path)
    snap = GuildSnapshot(
        id=42, name="Ping", owner_id=1, bot_role_id=2, bot_permissions=0,
        channels=[Channel(id=7, name="geral", type=ChannelType.GUILD_TEXT)],
        roles=[Role(id=3, name="Azul", color=0x3498DB)],
    )
    caminho = loja.salvar(42, snap, autor="ek8a", resumo="3 criar canal", versao=2)
    assert caminho.exists()

    dados = loja.ler(42)
    assert dados["versao"] == 2
    assert dados["autor"] == "ek8a"
    assert dados["resumo"] == "3 criar canal"
    assert dados["guild_id"] == 42
    assert dados["salvo_em"] > 0
    assert dados["canais"][0]["name"] == "geral"
    assert dados["cargos"][0]["name"] == "Azul"


def test_ler_guild_sem_snapshot_devolve_none(tmp_path):
    assert SnapshotStore(tmp_path).ler(999) is None


def test_um_arquivo_por_guild(tmp_path):
    """Isolamento (spec 8): o snapshot de um guild nao pode conter o de outro."""
    from atlas.models import GuildSnapshot

    loja = SnapshotStore(tmp_path)
    for gid in (1, 2):
        loja.salvar(gid, GuildSnapshot(id=gid, name=f"G{gid}", owner_id=1,
                                       bot_role_id=2, bot_permissions=0))
    assert loja.ler(1)["servidor"] == "G1"
    assert loja.ler(2)["servidor"] == "G2"


# --------------------------------------------------------------------- rollback
def test_rollback_inverte_criacoes_na_ordem_contraria():
    plano = plano_de_rollback([
        _Resultado("create_category", novo_id="10"),
        _Resultado("create_channel", novo_id="11"),
        _Resultado("create_role", novo_id="12"),
    ])
    assert [p["name"] for p in plano] == ["delete_role", "delete_channel", "delete_category"]
    assert plano[0]["args"] == {"role_id": "12"}
    assert plano[1]["args"] == {"channel_id": "11"}
    assert plano[2]["args"] == {"category_id": "10"}


def test_rollback_ignora_o_que_falhou():
    """Nao da para desfazer o que nao aconteceu."""
    plano = plano_de_rollback([
        _Resultado("create_channel", ok=True, novo_id="11"),
        _Resultado("create_channel", ok=False),
    ])
    assert len(plano) == 1


def test_rollback_nao_inventa_inversa_para_edicao():
    """Recriar nao restaura id, historico nem permissao. Melhor nao fingir."""
    assert plano_de_rollback([_Resultado("edit_channel")]) == []
    assert plano_de_rollback([_Resultado("delete_channel")]) == []


# ---------------------------------------------------------------- ponta a ponta
def test_plano_grande_salva_snapshot(harness, tmp_path):
    from atlas.snapshot_store import SnapshotStore

    muitas = [("create_channel", {"name": f"c{i}", "type": "text"}) for i in range(6)]
    h = harness([turn(*muitas), final("ok")], seed=False)
    h.agent.executor.snapshots = SnapshotStore(tmp_path)
    h.ctx.source_author_name = "ek8a"

    h.ask("monta 6 canais")
    h.ask("sim")

    dados = h.agent.executor.snapshots.ler(h.gateway.guild_id)
    assert dados is not None, "plano com 6 acoes tinha que salvar snapshot"
    assert dados["autor"] == "ek8a"
    assert dados["resumo"], "o resumo da mudanca tem que ficar registrado (spec 88)"


def test_plano_pequeno_nao_salva_snapshot(harness, tmp_path):
    from atlas.snapshot_store import SnapshotStore

    h = harness([turn(("create_channel", {"name": "um", "type": "text"})), final("ok")],
                seed=False)
    h.agent.executor.snapshots = SnapshotStore(tmp_path)
    h.ask("cria um canal")
    assert h.agent.executor.snapshots.ler(h.gateway.guild_id) is None


# ------------------------------------------- Fase 13: versionamento (spec 88)
def test_cada_salvamento_vira_uma_versao(tmp_path):
    from atlas.models import GuildSnapshot

    loja = SnapshotStore(tmp_path)
    for i in range(3):
        loja.salvar(7, GuildSnapshot(id=7, name=f"V{i}", owner_id=1,
                                     bot_role_id=2, bot_permissions=0),
                    autor="ek8a", resumo=f"mudanca {i}")

    versoes = loja.listar_versoes(7)
    assert [v["versao"] for v in versoes] == [1, 2, 3], "versao tem que subir sozinha"
    assert versoes[0]["resumo"] == "mudanca 0"
    assert versoes[2]["autor"] == "ek8a"
    assert all(v["salvo_em"] > 0 for v in versoes)


def test_da_para_ler_uma_versao_especifica(tmp_path):
    from atlas.models import GuildSnapshot

    loja = SnapshotStore(tmp_path)
    for i in range(3):
        loja.salvar(7, GuildSnapshot(id=7, name=f"V{i}", owner_id=1,
                                     bot_role_id=2, bot_permissions=0))

    v2 = loja.ler_versao(7, 2)
    assert v2 is not None and v2["servidor"] == "V1"
    assert loja.ler_versao(7, 99) is None, "versao que nao existe devolve None"


def test_ultima_versao_e_a_mais_recente(tmp_path):
    from atlas.models import GuildSnapshot

    loja = SnapshotStore(tmp_path)
    assert loja.ultima_versao(7) is None
    loja.salvar(7, GuildSnapshot(id=7, name="A", owner_id=1, bot_role_id=2,
                                 bot_permissions=0))
    loja.salvar(7, GuildSnapshot(id=7, name="B", owner_id=1, bot_role_id=2,
                                 bot_permissions=0))
    assert loja.ultima_versao(7) == 2
    assert loja.ler(7)["servidor"] == "B", "o arquivo 'ultimo estado' continua valendo"


def test_historico_aguenta_linha_corrompida(tmp_path):
    """Uma linha quebrada nao pode invalidar o historico inteiro."""
    from atlas.models import GuildSnapshot

    loja = SnapshotStore(tmp_path)
    loja.salvar(7, GuildSnapshot(id=7, name="A", owner_id=1, bot_role_id=2,
                                 bot_permissions=0))
    hist = loja._historico(7)
    hist.write_text(hist.read_text(encoding="utf-8") + "{isso nao e json\n",
                    encoding="utf-8")
    loja.salvar(7, GuildSnapshot(id=7, name="B", owner_id=1, bot_role_id=2,
                                 bot_permissions=0))

    versoes = loja.listar_versoes(7)
    # a linha ruim some e a numeracao segue contigua (1 -> 2), porque
    # proxima_versao() conta as versoes legiveis, nao as linhas do arquivo
    assert [v["versao"] for v in versoes] == [1, 2], versoes


def test_historico_e_isolado_por_guild(tmp_path):
    from atlas.models import GuildSnapshot

    loja = SnapshotStore(tmp_path)
    loja.salvar(1, GuildSnapshot(id=1, name="G1", owner_id=1, bot_role_id=2,
                                 bot_permissions=0))
    loja.salvar(2, GuildSnapshot(id=2, name="G2", owner_id=1, bot_role_id=2,
                                 bot_permissions=0))
    assert len(loja.listar_versoes(1)) == 1
    assert len(loja.listar_versoes(2)) == 1
    assert loja.ler_versao(1, 1)["servidor"] == "G1"


# ------------------------------------------------- spec 87: rollback de exclusão
def _res(tool, id_alvo, ok=True):
    from atlas.queue import ActionResult, PlannedAction

    return ActionResult(
        action=PlannedAction(tool=tool, params={"channel_id" if "channel" in tool or "category" in tool else "role_id": id_alvo}),
        ok=ok, data={},
    )


def _snap_com(id_canal=11, id_cargo=22):
    from atlas.models import Channel, ChannelType, GuildSnapshot, Role

    return GuildSnapshot(
        id=1, name="S", owner_id=1, bot_role_id=9, bot_permissions=0,
        channels=[Channel(id=id_canal, name="regras", type=ChannelType.GUILD_TEXT,
                          parent_id=5, topic="leia antes", nsfw=False, slowmode_delay=10)],
        roles=[Role(id=id_cargo, name="Moderador", position=3, color=0xFF0000,
                    permissions=0, hoist=True, mentionable=False)],
    )


def test_restauracao_recria_canal_com_os_dados_do_snapshot():
    from atlas.snapshot_store import plano_de_restauracao

    plano, perdas = plano_de_restauracao(_snap_com(), [_res("delete_channel", 11)])
    assert len(plano) == 1
    args = plano[0]["args"]
    assert plano[0]["name"] == "create_channel"
    assert args["name"] == "regras"
    assert args["topic"] == "leia antes"
    assert args["parent_id"] == "5"


def test_restauracao_recria_cargo():
    from atlas.snapshot_store import plano_de_restauracao

    plano, _ = plano_de_restauracao(_snap_com(), [_res("delete_role", 22)])
    assert plano[0]["name"] == "create_role"
    assert plano[0]["args"]["name"] == "Moderador"
    assert plano[0]["args"]["color"] == 0xFF0000


def test_restauracao_diz_o_que_nao_volta():
    """Spec 185: prometer 'desfeito' inteiro seria sucesso falso."""
    from atlas.snapshot_store import plano_de_restauracao

    _, perdas = plano_de_restauracao(_snap_com(), [_res("delete_channel", 11)])
    assert perdas, "tinha que listar as perdas"
    assert any("histórico de mensagens" in p for p in perdas)
    assert any("regras" in p for p in perdas), "a perda tem que dizer de qual canal"


def test_restauracao_de_cargo_avisa_que_membros_perdem_o_cargo():
    from atlas.snapshot_store import plano_de_restauracao

    _, perdas = plano_de_restauracao(_snap_com(), [_res("delete_role", 22)])
    assert any("cargo dos membros" in p for p in perdas)


def test_restauracao_nao_inventa_quando_o_snapshot_nao_tem():
    from atlas.snapshot_store import plano_de_restauracao

    plano, perdas = plano_de_restauracao(_snap_com(), [_res("delete_channel", 999)])
    assert plano == []
    assert perdas == []


def test_restauracao_ignora_acao_que_falhou():
    from atlas.snapshot_store import plano_de_restauracao

    plano, _ = plano_de_restauracao(_snap_com(), [_res("delete_channel", 11, ok=False)])
    assert plano == []


def test_restauracao_ignora_acao_que_nao_e_exclusao():
    """Criar não entra aqui - isso é o plano_de_rollback, que é reversível de
    verdade. Misturar os dois faria 'restaurar' excluir o que foi criado."""
    from atlas.queue import ActionResult, PlannedAction
    from atlas.snapshot_store import plano_de_restauracao

    r = ActionResult(action=PlannedAction(tool="create_channel", params={"name": "x"}),
                     ok=True, data={"created": {"id": 77}})
    plano, _ = plano_de_restauracao(_snap_com(), [r])
    assert plano == []


def test_restauracao_devolve_tupla_de_proposito():
    """Devolver só o plano convidaria o chamador a apresentar como 'desfeito'.
    A tupla obriga a olhar para as perdas."""
    from atlas.snapshot_store import plano_de_restauracao

    resultado = plano_de_restauracao(_snap_com(), [_res("delete_channel", 11)])
    assert isinstance(resultado, tuple) and len(resultado) == 2
