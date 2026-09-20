#!/usr/bin/env python3
"""Gera o razão das seções da MASTER SPECIFICATION (docs/SPEC-LEDGER.md).

POR QUE ISTO EXISTE
-------------------
A spec tem 187 seções. Eu entreguei 23 fases e agrupei as seções em numeração
minha, o que escondeu o buraco: não havia como auditar o que faltava. Este
script é a correção estrutural desse erro.

REGRAS ANTI-INVENÇÃO (o motivo de não ser uma tabela escrita à mão)
-------------------------------------------------------------------
1. **Default é ABERTA.** Nenhuma seção nasce "pronta". Só fica pronta se houver
   entrada explícita em `_EVIDENCIAS` — e cada entrada cita arquivo ou commit.
2. **A evidência é verificada.** Se o arquivo citado não existe, ou o commit não
   está no histórico, o script FALHA. Não dá para marcar pronto apontando para
   coisa que não existe.
3. **Seção fantasma é erro.** Se `_EVIDENCIAS` cita um número que não está em
   docs/SPEC.md, o script falha: impede status de seção que a spec não tem.
4. **Nada de chute por nome.** O status não é inferido de grep em src/ — grep
   prova que uma palavra aparece, não que o requisito foi implementado.

USO
    python scripts/spec_ledger.py            # gera docs/SPEC-LEDGER.md
    python scripts/spec_ledger.py --checar   # só valida, nao escreve
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SPEC = RAIZ / "docs" / "SPEC.md"
LEDGER = RAIZ / "docs" / "SPEC-LEDGER.md"

#: Status possíveis. Sem meio-termo ambíguo: ou tem evidência, ou está aberta.
PRONTA = "PRONTA"
PARCIAL = "PARCIAL"
ABERTA = "ABERTA"
FORA = "FORA DE ESCOPO"

#: Seção -> (status, evidência, observação).
#: A evidência tem que existir de verdade: o script confere.
_EVIDENCIAS: dict[int, tuple[str, str, str]] = {
    11: (PARCIAL, "src/atlas/design.py", "proposta é gerada, mas plano != execução ainda depende do modelo seguir"),
    12: (PRONTA, "46b867f", "dry run / simulação"),
    21: (PRONTA, "src/atlas/dependencias.py", "ordenação por dependência de execução"),
    25: (PRONTA, "src/atlas/autofix.py", "auto-correção antes de falhar"),
    26: (PRONTA, "src/atlas/design_system.py", "composição domínio x porte x público x estilo"),
    27: (PRONTA, "tests/test_design_system.py", "domínios diferentes dão estruturas diferentes"),
    32: (PRONTA, "src/atlas/catalogo.py", "padrões marcados NÃO VERIFICADO, sem fonte inventada"),
    33: (PRONTA, "src/atlas/catalogo.py", "confiança por padrão"),
    35: (PRONTA, "src/atlas/design_system.py", "13 estilos visuais"),
    36: (PRONTA, "src/atlas/design_system.py", "nomenclatura uniforme, sem misturar"),
    37: (PRONTA, "src/atlas/design_system.py", "áreas conceituais com propósito"),
    38: (PRONTA, "src/atlas/design_system.py", "todo canal tem propósito declarado"),
    40: (PRONTA, "src/atlas/design_system.py", "funcional x identidade separados"),
    41: (PRONTA, "src/atlas/design_system.py", "hierarquia cresce com o porte"),
    42: (PRONTA, "src/atlas/design_system.py", "nenhum funcional nasce com administrator"),
    43: (PRONTA, "src/atlas/design_system.py", "jornada de onboarding por domínio"),
    44: (PRONTA, "src/atlas/design_system.py", "porte corta a arquitetura"),
    73: (PRONTA, "src/atlas/botoes.py", "as sete barreiras do clique"),
    78: (PRONTA, "tests/test_design_system.py", "tema sozinho não muda a estrutura"),
    79: (PRONTA, "tests/test_design_system.py", "público muda a estrutura"),
    86: (PRONTA, "1991c78", "backup lógico"),
    87: (PARCIAL, "1991c78", "rollback só inverte criações"),
    88: (PRONTA, "src/atlas/versionamento.py", "JSONL por guild"),
    89: (PRONTA, "3cadac1", "task system com estados"),
    90: (PRONTA, "76ae5c1", "cancelamento de tarefa"),
    93: (PRONTA, "src/atlas/recuperacao.py", "classifica pós-restart, não executa"),
    107: (PRONTA, "src/atlas/ai/classificacao.py", "classe da tarefa influencia a rota"),
    113: (PRONTA, "src/atlas/estados.py", "estados do agente"),
    115: (PRONTA, "src/atlas/ai/classificacao.py", "prioridade de rota"),
    119: (PRONTA, "src/atlas/catalogo.py", "filtro por confiança mínima"),
    130: (PARCIAL, "src/atlas/design.py", "proposta concreta entra no prompt"),
    135: (PRONTA, "src/atlas/design_system.py", "briefing antes de qualquer canal"),
    136: (PRONTA, "src/atlas/design_system.py", "7 critérios com pontos e motivo"),
    137: (PRONTA, "src/atlas/design_system.py", "precisa_refazer, limiar 8.0"),
    138: (PRONTA, "src/atlas/design_system.py", "domínio x porte x público x estilo"),
    140: (PRONTA, "src/atlas/catalogo.py", "feedback por guild, promover exige fonte"),
    149: (PRONTA, "src/atlas/flow_control.py", "backpressure"),
    150: (PRONTA, "src/atlas/flow_control.py", "cota por guild em janela"),
    156: (PRONTA, "76ae5c1", "progresso parcial"),
    158: (PRONTA, "76ae5c1", "cancelamento cooperativo"),
    169: (PRONTA, "tests/test_design_system.py", "compara forma pelo propósito, nunca pelo nome"),
}

#: Seções deliberadamente fora, com o motivo. Não é "esqueci": é decisão.
_FORA: dict[int, str] = {
    28: "pesquisa na web: 21 tools fixas, todas de operação no Discord",
    29: "pesquisa na web",
    30: "pesquisa na web",
    31: "pesquisa na web",
    33: "pesquisa na web (o catálogo existe, os padrões pesquisados não)",
    75: "pesquisa na web",
    116: "verificada como satisfeita por ausência: nada atrasa pedido simples",
}


def _rel(caminho: Path) -> str:
    """Caminho para mostrar. relative_to() estoura se o arquivo estiver fora do
    repo (e os testes apontam para tmp), entao cai no caminho absoluto."""
    try:
        return str(caminho.relative_to(RAIZ))
    except ValueError:
        return str(caminho)


def _git_tem(commit: str) -> bool:
    r = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=RAIZ, capture_output=True,
    )
    return r.returncode == 0


def parsear_secoes(texto: str) -> dict[int, str]:
    """Extrai número -> título da spec.

    Aceita os formatos usuais: "12." no início da linha, "## 12 -", "SEÇÃO 12:".
    Não tenta adivinhar seção que não está numerada no texto.
    """
    padroes = [
        re.compile(r"^#{0,4}\s*(\d{1,3})[.)\-:]\s*(.+)$", re.MULTILINE),
        re.compile(r"^SE[CÇ][AÃ]O\s+(\d{1,3})\s*[-:.]?\s*(.*)$", re.MULTILINE | re.IGNORECASE),
    ]
    out: dict[int, str] = {}
    for p in padroes:
        for m in p.finditer(texto):
            n = int(m.group(1))
            titulo = (m.group(2) or "").strip()
            # Primeiro que casar vence; títulos repetidos não sobrescrevem um bom.
            if n not in out or (not out[n] and titulo):
                out[n] = titulo
    return out


def main() -> int:
    checar = "--checar" in sys.argv

    if not SPEC.exists():
        print(f"ERRO: {_rel(SPEC)} não existe.")
        print("Cole a MASTER SPECIFICATION nesse arquivo antes de gerar o razão.")
        return 2

    secoes = parsear_secoes(SPEC.read_text(encoding="utf-8"))
    if not secoes:
        print(f"ERRO: nenhuma seção numerada foi encontrada em {_rel(SPEC)}.")
        print("O parser procura linhas como '12. Título' ou '## 12 - Título'.")
        return 2

    erros: list[str] = []

    # Regra 3: status de seção que a spec não tem é erro.
    for n in sorted(set(_EVIDENCIAS) | set(_FORA)):
        if n not in secoes:
            erros.append(f"seção {n} tem status mas não existe em docs/SPEC.md")

    # Regra 2: a evidência tem que existir.
    for n, (status, evid, _obs) in sorted(_EVIDENCIAS.items()):
        if status == FORA:
            continue
        if re.fullmatch(r"[0-9a-f]{7,40}", evid):
            if not _git_tem(evid):
                erros.append(f"seção {n}: commit {evid} não está no histórico")
        else:
            alvo = RAIZ / evid
            if not alvo.exists():
                erros.append(f"seção {n}: arquivo {evid} não existe")

    if erros:
        print("RAZÃO INVÁLIDO — nada foi escrito:")
        for e in erros:
            print(f"  - {e}")
        return 1

    linhas = [
        "# Razão da MASTER SPECIFICATION",
        "",
        "Gerado por `scripts/spec_ledger.py`. **Não editar à mão** — o script",
        "confronta cada evidência com o repositório e falha se ela não existir.",
        "Default é `ABERTA`: seção só sai de aberta com evidência verificada.",
        "",
        f"Seções na spec: **{len(secoes)}**",
        "",
        "| # | Seção | Estado | Evidência | Obs. |",
        "|---|---|---|---|---|",
    ]

    contagem = {PRONTA: 0, PARCIAL: 0, ABERTA: 0, FORA: 0}
    for n in sorted(secoes):
        titulo = secoes[n][:70]
        if n in _EVIDENCIAS:
            status, evid, obs = _EVIDENCIAS[n]
        elif n in _FORA:
            status, evid, obs = FORA, "decisão", _FORA[n]
        else:
            status, evid, obs = ABERTA, "—", ""
        contagem[status] += 1
        linhas.append(f"| {n} | {titulo} | {status} | `{evid}` | {obs} |")

    resumo = [
        "",
        "## Resumo",
        "",
        f"- PRONTA: **{contagem[PRONTA]}**",
        f"- PARCIAL: **{contagem[PARCIAL]}**",
        f"- ABERTA: **{contagem[ABERTA]}**",
        f"- FORA DE ESCOPO: **{contagem[FORA]}**",
        f"- Total: **{len(secoes)}**",
        "",
        "Se a soma não bater com o total, o parser perdeu seção: conserte o parser,",
        "não o número.",
    ]
    texto = "\n".join(linhas + resumo) + "\n"

    if checar:
        print(f"OK: {len(secoes)} seções, evidências conferem.")
        print(f"  PRONTA={contagem[PRONTA]} PARCIAL={contagem[PARCIAL]} "
              f"ABERTA={contagem[ABERTA]} FORA={contagem[FORA]}")
        return 0

    LEDGER.write_text(texto, encoding="utf-8")
    print(f"escrito {_rel(LEDGER)}: {len(secoes)} secoes")
    print(f"  PRONTA={contagem[PRONTA]} PARCIAL={contagem[PARCIAL]} "
          f"ABERTA={contagem[ABERTA]} FORA={contagem[FORA]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
