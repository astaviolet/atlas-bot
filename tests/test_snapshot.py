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
