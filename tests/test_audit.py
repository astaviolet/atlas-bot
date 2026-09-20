"""Auditoria: estrutura do registro e garantia de que credencial nao vaza."""

from __future__ import annotations

import json
import logging

import pytest

from atlas.audit import AuditLog, SecretRedactingFilter, redact, safe_params



SECRETOS = [
    "ghp_1234567890abcdefghijklmnopqrstuvwx",
    "github_pat_11ABCDEF0123456789abcdefghijklmnOPQRSTUVWXYZ",
    "AIzaSyA-1234567890abcdefghijklmnopqrstuv",
    "sk-1234567890abcdefghijklmnopqrstuvwx",
    # Montado por concatenacao de proposito: o literal completo tem o formato
    # exato de um token real do Discord e o Push Protection do GitHub barra o
    # push. Assim o teste continua exercitando o padrao verdadeiro sem que a
    # string apareca inteira no arquivo.
    "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ" + "." + "Gh1jKl" + "." + "mnopqrstuvwxyzABCDEFGHIJKLM",
]


@pytest.mark.parametrize("segredo", SECRETOS)
def test_segredo_e_mascarado(segredo):
    saida = redact(f"token={segredo} no meio do texto")
    assert segredo not in saida
    assert "REDACTED" in saida


def test_filtro_de_logging_mascara_antes_do_handler(caplog):
    logger = logging.getLogger("atlas.test.redaction")
    logger.handlers.clear()
    logger.propagate = True
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture()
    handler.addFilter(SecretRedactingFilter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("conectando com %s", SECRETOS[0])
    assert records, "handler nao capturou"
    assert SECRETOS[0] not in records[0]
    assert "REDACTED" in records[0]


def test_parametros_sensiveis_nao_sao_auditados():
    params = {
        "name": "canal",
        "token": "ghp_segredo1234567890abcdefgh",
        "api_key": "AIzaSyA1234567890abcdefghijklmno",
        "password": "senha",
        "authorization": "Bearer x",
    }
    saida = safe_params(params)
    assert "token" not in saida
    assert "api_key" not in saida
    assert "password" not in saida
    assert "authorization" not in saida
    assert saida["name"] == "canal"


def test_registro_de_auditoria_tem_os_campos_exigidos(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit = AuditLog(path)
    entry = audit.record(
        action="create_channel",
        user_id=1,
        guild_id=2,
        channel_id=3,
        params={"name": "geral", "type": "text"},
        result="ok",
    )
    for campo in ("iso", "action", "user_id", "guild_id", "channel_id", "params", "result"):
        assert campo in entry, f"campo {campo} ausente"

    linhas = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(linhas) == 1
    gravado = json.loads(linhas[0])
    assert gravado["action"] == "create_channel"
    assert gravado["result"] == "ok"


def test_erro_tambem_e_registrado_com_erro_mascarado(tmp_path):
    audit = AuditLog(tmp_path / "a.jsonl")
    entry = audit.record(action="x", result="error", error=f"falhou com {SECRETOS[3]}")
    assert entry["result"] == "error"
    assert SECRETOS[3] not in json.dumps(entry)


def test_parametro_longo_e_truncado():
    saida = safe_params({"descricao": "a" * 500})
    assert len(saida["descricao"]) < 250
    assert "truncado" in saida["descricao"]
