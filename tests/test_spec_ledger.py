"""O gerador do razão da spec (regra anti-invenção)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "spec_ledger", _RAIZ / "scripts" / "spec_ledger.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _spec_de_exemplo(tmp_path: Path) -> Path:
    """Uma spec pequena com todas as seções citadas em _EVIDENCIAS/_FORA."""
    nums = sorted(set(mod._EVIDENCIAS) | set(mod._FORA))
    corpo = "\n\n".join(f"{n}. Requisito número {n}" for n in nums)
    p = tmp_path / "SPEC.md"
    p.write_text("# MASTER SPECIFICATION\n\n" + corpo + "\n", encoding="utf-8")
    return p


def _apontar(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "SPEC", _spec_de_exemplo(tmp_path))
    alvo = tmp_path / "SPEC-LEDGER.md"
    monkeypatch.setattr(mod, "LEDGER", alvo)
    return alvo


def test_parser_pega_secao_numerada(tmp_path, monkeypatch):
    _apontar(tmp_path, monkeypatch)
    secoes = mod.parsear_secoes(mod.SPEC.read_text(encoding="utf-8"))
    assert 12 in secoes and secoes[12] == "Requisito número 12"
    assert len(secoes) == len(set(mod._EVIDENCIAS) | set(mod._FORA))


def test_default_e_aberta(tmp_path, monkeypatch):
    """Regra 1: nada nasce pronto."""
    alvo = _apontar(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "_EVIDENCIAS", {})
    monkeypatch.setattr(mod, "_FORA", {})
    monkeypatch.setattr(mod.sys, "argv", ["spec_ledger.py"])
    assert mod.main() == 0
    texto = alvo.read_text(encoding="utf-8")
    assert "| ABERTA |" in texto
    assert "| PRONTA |" not in texto
    assert "PRONTA: **0**" in texto


def test_evidencia_de_arquivo_inexistente_derruba(tmp_path, monkeypatch):
    """Regra 2: não dá para marcar pronto apontando para arquivo que não existe."""
    _apontar(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "_EVIDENCIAS", {12: (mod.PRONTA, "src/atlas/nao_existe.py", "x")})
    monkeypatch.setattr(mod, "_FORA", {})
    monkeypatch.setattr(mod.sys, "argv", ["spec_ledger.py"])
    assert mod.main() == 1
    assert not (tmp_path / "SPEC-LEDGER.md").exists(), "não pode escrever razão inválido"


def test_evidencia_de_commit_inexistente_derruba(tmp_path, monkeypatch):
    _apontar(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "_EVIDENCIAS", {12: (mod.PRONTA, "deadbeefdeadbeef", "x")})
    monkeypatch.setattr(mod, "_FORA", {})
    monkeypatch.setattr(mod.sys, "argv", ["spec_ledger.py"])
    assert mod.main() == 1


def test_commit_real_passa(tmp_path, monkeypatch):
    """O outro lado: commit que existe de verdade tem que ser aceito."""
    _apontar(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "_EVIDENCIAS", {12: (mod.PRONTA, "46b867f", "dry run")})
    monkeypatch.setattr(mod, "_FORA", {})
    monkeypatch.setattr(mod.sys, "argv", ["spec_ledger.py"])
    assert mod.main() == 0
    assert "| 12 | Requisito número 12 | PRONTA | `46b867f` | dry run |" in \
        (tmp_path / "SPEC-LEDGER.md").read_text(encoding="utf-8")


def test_secao_fantasma_derruba(tmp_path, monkeypatch):
    """Regra 3: status de seção que a spec não tem é erro."""
    _apontar(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "_EVIDENCIAS", {999: (mod.PRONTA, "src/atlas/design.py", "x")})
    monkeypatch.setattr(mod, "_FORA", {})
    monkeypatch.setattr(mod.sys, "argv", ["spec_ledger.py"])
    assert mod.main() == 1


def test_checar_nao_escreve(tmp_path, monkeypatch):
    alvo = _apontar(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "_EVIDENCIAS", {})
    monkeypatch.setattr(mod, "_FORA", {})
    monkeypatch.setattr(mod.sys, "argv", ["spec_ledger.py", "--checar"])
    assert mod.main() == 0
    assert not alvo.exists()


def test_sem_spec_avisa_em_vez_de_chutar(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "SPEC", tmp_path / "nao_tem.md")
    monkeypatch.setattr(mod.sys, "argv", ["spec_ledger.py"])
    assert mod.main() == 2
