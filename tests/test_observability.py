"""Fase 9: observabilidade (spec 68/121/122)."""

from __future__ import annotations

from atlas.observability import (
    formatar_painel_geral,
    responder_as_tres_perguntas,
    resumo_auditoria,
)


def _reg(action, result="ok", error=None, guild=1):
    return {"ts": 1, "iso": "2026-09-20T23:00:00Z", "action": action,
            "guild_id": guild, "result": result, "error": error}


def test_resumo_conta_ok_e_falha():
    r = resumo_auditoria([
        _reg("create_channel"), _reg("create_channel"),
        _reg("delete_role", "error", "acima do cargo do bot"),
    ])
    assert r["total_eventos"] == 3
    assert r["ok"] == 2 and r["falhas"] == 1
    assert r["taxa_de_falha"] == round(1 / 3, 3)
    assert r["por_acao"]["create_channel"] == 2
    assert r["guilds_distintos"] == 1


def test_resumo_separa_guilds():
    r = resumo_auditoria([_reg("create_channel", guild=1), _reg("create_channel", guild=2)])
    assert r["guilds_distintos"] == 2


def test_resumo_vazio_nao_divide_por_zero():
    r = resumo_auditoria([])
    assert r["taxa_de_falha"] == 0.0
    assert r["total_eventos"] == 0


def test_resumo_aguenta_linha_corrompida():
    r = resumo_auditoria([_reg("create_channel"), "nao e dict", None])
    assert r["total_eventos"] == 1


def test_as_tres_perguntas_apontam_a_falha():
    r = resumo_auditoria([_reg("create_channel"), _reg("delete_role", "error", "sem permissao")])
    linhas = responder_as_tres_perguntas(r)
    assert len(linhas) == 3
    assert linhas[0].startswith("o que aconteceu")
    assert "delete_role" in linhas[1] and "sem permissao" in linhas[1]
    assert linhas[2].startswith("o que agora")


def test_painel_avisa_quando_a_ia_esta_morta():
    r = resumo_auditoria([_reg("create_channel")])
    texto = formatar_painel_geral(r, ai={"rotas": 12, "rotas_saudaveis": 0})
    assert "nenhuma rota de IA respondeu" in texto


def test_painel_avisa_pool_degradado_e_mostra_numeros():
    r = resumo_auditoria([_reg("create_channel")])
    texto = formatar_painel_geral(r, ai={"rotas": 12, "rotas_saudaveis": 3, "fallbacks": 7})
    assert "degradado" in texto
    assert "fallbacks" in texto and "7" in texto


def test_painel_diz_que_esta_bem():
    r = resumo_auditoria([_reg("create_channel")])
    texto = formatar_painel_geral(r, ai={"rotas": 12, "rotas_saudaveis": 12})
    assert "nada. 12 de 12 rotas saudaveis" in texto


def test_cli_painel_roda_sem_gastar_cota(tmp_path, monkeypatch):
    """--painel nao pode re-sondar: --health leva 138s e queima a cota gratuita."""
    import json

    import main as main_mod

    log = tmp_path / "audit.jsonl"
    log.write_text(json.dumps({
        "ts": 1, "iso": "2026-09-20T23:00:00Z", "action": "create_channel",
        "guild_id": 1, "result": "error", "error": "estourou a cota",
    }) + "\n", encoding="utf-8")

    lidos = []
    original = main_mod._ler_auditoria_do_disco
    monkeypatch.setattr(
        main_mod, "_ler_auditoria_do_disco",
        lambda caminho: lidos.append(caminho) or original(caminho),
    )

    rc = main_mod.main.__wrapped__() if hasattr(main_mod.main, "__wrapped__") else None
    if rc is None:
        import sys
        monkeypatch.setattr(sys, "argv", ["main.py", "--painel"])
        monkeypatch.setenv("ATLAS_AUDIT_PATH", str(log))
        rc = main_mod.main()

    assert rc == 0
    assert lidos, "o painel tem que ler o historico do disco"
