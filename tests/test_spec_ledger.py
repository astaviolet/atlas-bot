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
    # Título em CAIXA ALTA: é assim que a spec real marca cabeçalho de seção,
    # e o parser exige isso para não confundir com item de lista numerada.
    corpo = "\n\n".join(f"{n}. REQUISITO NUMERO {n}" for n in nums)
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
    assert 12 in secoes and secoes[12] == "REQUISITO NUMERO 12"
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
    """O outro lado: commit que existe de verdade tem que ser aceito.

    Usa HEAD em vez de um sha fixo de proposito. Este teste tinha "46b867f"
    escrito na mão: passa local, onde o histórico é completo, e QUEBROU no
    GitHub Actions, cujo checkout é raso (depth 1) e não tem commit antigo. A
    falha derrubou o job de testes e o job do bot foi pulado - ou seja, um sha
    decorativo deixou o bot fora do ar. HEAD existe em qualquer clone.
    """
    import subprocess

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
    ).stdout.strip()

    _apontar(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "_EVIDENCIAS", {12: (mod.PRONTA, head, "dry run")})
    monkeypatch.setattr(mod, "_FORA", {})
    monkeypatch.setattr(mod.sys, "argv", ["spec_ledger.py"])
    assert mod.main() == 0
    assert f"| 12 | REQUISITO NUMERO 12 | PRONTA | `{head}` | dry run |" in \
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


def test_item_de_lista_numerada_nao_vira_secao(tmp_path, monkeypatch):
    """Caso real da spec: a seção 54 tem '2. OAuth legítimo;' na lista.
    Sem o filtro de caixa alta o parser inventava uma seção 2 com esse título."""
    alvo = _apontar(tmp_path, monkeypatch)
    mod.SPEC.write_text(
        "54. NO-KEY / FREE-FIRST\n\nPriorizar:\n\n1. acesso sem chave;\n"
        "2. OAuth legítimo;\n3. free tier;\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_EVIDENCIAS", {})
    monkeypatch.setattr(mod, "_FORA", {})
    monkeypatch.setattr(mod.sys, "argv", ["spec_ledger.py"])
    assert mod.main() == 0
    secoes = mod.parsear_secoes(mod.SPEC.read_text(encoding="utf-8"))
    assert list(secoes) == [54], secoes
    assert "OAuth" not in alvo.read_text(encoding="utf-8")


def test_spec_real_tem_188_secoes():
    """Contra docs/SPEC.md de verdade: 0 a 187, sem buraco."""
    spec = _RAIZ / "docs" / "SPEC.md"
    if not spec.exists():
        import pytest
        pytest.skip("docs/SPEC.md ainda não foi salvo")
    secoes = mod.parsear_secoes(spec.read_text(encoding="utf-8"))
    assert len(secoes) == 188, len(secoes)
    faltando = [n for n in range(188) if n not in secoes]
    assert not faltando, f"seções ausentes: {faltando}"
    assert secoes[0].startswith("MISSÃO")
    assert secoes[187].startswith("PRIMEIRA AÇÃO")


def test_mapa_de_evidencias_nao_tem_chave_duplicada():
    """Chave repetida em literal de dict: a ultima vence EM SILENCIO. Aconteceu
    de verdade com a secao 156 - duas entradas, uma apontando para commit e outra
    para teste, e o ruff foi o unico que avisou. Teste para nao depender do ruff."""
    fonte = (_RAIZ / "scripts" / "spec_ledger.py").read_text(encoding="utf-8")
    import re
    chaves = re.findall(r"^\s+(\d{1,3}): \(", fonte, re.MULTILINE)
    repetidas = {c for c in chaves if chaves.count(c) > 1}
    assert not repetidas, f"seções com entrada duplicada: {sorted(repetidas)}"


def test_evidencia_de_pronta_e_teste_ou_commit():
    """Regra 5 (spec 160) conferida de novo por dentro: se alguem marcar PRONTA
    apontando para src/, este teste falha junto com o script."""
    import re
    for n, (status, evid, _obs) in mod._EVIDENCIAS.items():
        if status != mod.PRONTA:
            continue
        if re.fullmatch(r"[0-9a-f]{7,40}", evid):
            continue
        assert evid.startswith("tests/"), (
            f"seção {n}: PRONTA aponta para {evid}, não para um teste (spec 160)"
        )
