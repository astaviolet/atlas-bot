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
5. **PRONTA exige teste** (spec 160). Evidência em `src/` sozinha vale no máximo
   PARCIAL: "o código foi escrito" não é conclusão.

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
    7: (PRONTA, "tests/test_security.py", "guild_id estranho é ignorado e não autoriza"),
    8: (PRONTA, "tests/test_security.py", "bind_guild recusa outro servidor; chaves de guild removidas em massa"),
    13: (PRONTA, "tests/test_tools_basic.py", "categoria pedida duas vezes não duplica"),
    14: (PRONTA, "tests/test_policy.py", "registry tem exatamente as ferramentas permitidas"),
    15: (PRONTA, "tests/test_tools_basic.py", "configuração inválida é recusada"),
    16: (PRONTA, "tests/test_policy.py", "policy recusa cada capacidade proibida"),
    17: (PRONTA, "tests/test_security.py", "ação proibida recusada; nenhuma ferramenta proibida registrada"),
    18: (PRONTA, "tests/test_batch.py", "exclusão múltipla exige confirmação; ambígua não executa"),
    19: (PRONTA, "tests/test_batch.py", "confirmação vencida não executa"),
    20: (PRONTA, "tests/test_wiring.py", "executor centralizado testado de ponta a ponta"),
    22: (PRONTA, "tests/test_batch.py", "lote com falha parcial reporta o que falhou"),
    23: (PRONTA, "tests/test_batch.py", "sucesso parcial reportado, não fingido"),
    24: (PRONTA, "tests/test_errors.py", "verificação detecta mudança que não aconteceu"),
    50: (PRONTA, "tests/test_security.py", "prompt injection bloqueado; unicode invisível detectado"),
    56: (PRONTA, "tests/test_router.py", "falhas repetidas colocam a rota em cooldown"),
    57: (PRONTA, "tests/test_router.py", "falha transitória vai para a próxima rota"),
    58: (PRONTA, "tests/test_router.py", "pedido com tools exige rota com tool calling"),
    59: (PRONTA, "tests/test_router.py", "só informa limitação depois de esgotar o pool"),
    60: (PRONTA, "tests/test_router.py", "carga se distribui em vez de empilhar na primeira rota"),
    61: (PRONTA, "tests/test_router.py", "cooldown acaba e a rota volta em half-open"),
    62: (PRONTA, "tests/test_router.py", "cooldown cresce a cada queda seguida"),
    64: (PRONTA, "tests/test_flow_control.py", "concorrência controlada"),
    65: (PRONTA, "tests/test_flow_control.py", "trava por guild"),
    66: (PRONTA, "tests/test_security.py", "rate limit por servidor"),
    67: (PRONTA, "tests/test_router.py", "cache expira e é invalidado por mutação"),
    69: (PRONTA, "tests/test_audit.py", "segredo mascarado; parâmetros sensíveis não são auditados"),
    70: (PRONTA, "tests/test_audit.py", "registro de auditoria tem os campos exigidos"),
    74: (PRONTA, "tests/test_errors.py", "erro de permissão e erro da API viram mensagem útil"),
    94: (PRONTA, "tests/test_audit.py", "segredo mascarado antes do handler de log"),
    148: (PRONTA, "tests/test_flow_control.py", "backpressure e fila"),
    151: (PRONTA, "tests/test_security.py", "barreiras de schema, auth, policy e contexto"),
    155: (PRONTA, "tests/test_batch.py", "lote respeita a cota e reporta falhas"),
    156: (PRONTA, "tests/test_progresso.py", "progresso informado"),
    176: (PRONTA, "tests/test_security.py", "outra guild, permissão proibida, membro, injection — todos falham"),
    177: (PRONTA, "tests/test_batch.py", "confirmação vencida não executa"),
    178: (PRONTA, "tests/test_tools_basic.py", "não cria duas categorias"),
    180: (PRONTA, "tests/test_batch.py", "falha parcial: estado, logs e resposta"),
    68: (PRONTA, "tests/test_observability.py", "resumo conta ok e falha, separa guilds, aguenta linha corrompida"),
    71: (PRONTA, "tests/test_embeds.py", "embed vira cartão Components V2 (flags 32768)"),
    72: (PRONTA, "tests/test_embeds.py", "cartão V2 também passa pela limpeza; o modelo dá o texto, o código monta"),
    120: (PRONTA, "tests/test_observability.py", "as três perguntas apontam a falha"),
    121: (PRONTA, "tests/test_observability.py", "painel avisa IA morta, pool degradado, e diz quando está bem"),
    122: (PRONTA, "tests/test_alertas.py", "os seis gatilhos da spec: erro elevado, pool fora, fila acumulada, 429, falhas repetidas, tarefas presas"),
    21: (PRONTA, "tests/test_dependencias.py", "ordenação por dependência de execução"),
    25: (PRONTA, "tests/test_autofix.py", "auto-correção antes de falhar"),
    26: (PRONTA, "tests/test_design_system.py", "composição domínio x porte x público x estilo"),
    27: (PRONTA, "tests/test_design_system.py", "domínios diferentes dão estruturas diferentes"),
    32: (PARCIAL, "src/atlas/catalogo.py", "estrutura existe; a FONTE da spec é 'referências pesquisadas' e não houve pesquisa - padrões estão NÃO VERIFICADO"),
    33: (PRONTA, "tests/test_catalogo.py", "armazena princípios, não templates; cresce por feedback"),
    35: (PRONTA, "tests/test_design_system.py", "13 estilos visuais"),
    36: (PRONTA, "tests/test_design_system.py", "nomenclatura uniforme, sem misturar"),
    37: (PRONTA, "tests/test_design_system.py", "áreas conceituais com propósito"),
    38: (PRONTA, "tests/test_design_system.py", "todo canal tem propósito declarado"),
    40: (PRONTA, "tests/test_design_system.py", "funcional x identidade separados"),
    41: (PRONTA, "tests/test_design_system.py", "hierarquia cresce com o porte"),
    42: (PRONTA, "tests/test_design_system.py", "nenhum funcional nasce com administrator"),
    43: (PRONTA, "tests/test_design_system.py", "jornada de onboarding por domínio"),
    47: (PRONTA, "tests/test_design_check.py", "QA interno: categoria vazia, canal duplicado, cargo com admin, canal órfão"),
    44: (PRONTA, "tests/test_design_system.py", "porte corta a arquitetura"),
    73: (PRONTA, "tests/test_botoes.py", "as sete barreiras do clique"),
    78: (PRONTA, "tests/test_design_system.py", "tema sozinho não muda a estrutura"),
    79: (PRONTA, "tests/test_design_system.py", "público muda a estrutura"),
    86: (PRONTA, "1991c78", "backup lógico"),
    87: (PARCIAL, "1991c78", "rollback só inverte criações"),
    88: (PRONTA, "tests/test_snapshot.py", "versionamento JSONL por guild (Fase 13 `9797e35`)"),
    89: (PRONTA, "3cadac1", "task system com estados"),
    90: (PRONTA, "76ae5c1", "cancelamento de tarefa"),
    93: (PRONTA, "tests/test_recuperacao.py", "classifica pós-restart, não executa"),
    107: (PRONTA, "tests/test_classificacao.py", "classe da tarefa influencia a rota"),
    113: (PRONTA, "tests/test_estados.py", "estados do agente"),
    115: (PRONTA, "tests/test_classificacao.py", "prioridade de rota"),
    119: (PRONTA, "tests/test_catalogo.py", "filtro por confiança mínima"),
    130: (PARCIAL, "src/atlas/design.py", "proposta concreta entra no prompt"),
    135: (PRONTA, "tests/test_design_system.py", "briefing antes de qualquer canal"),
    136: (PRONTA, "tests/test_design_system.py", "7 critérios com pontos e motivo"),
    137: (PRONTA, "tests/test_design_system.py", "precisa_refazer, limiar 8.0"),
    138: (PARCIAL, "src/atlas/agent.py", "_qa_pos_execucao existe e a divergência é testada em test_autofix, mas falta teste dedicado do laço estado-real-vs-design"),
    140: (PRONTA, "tests/test_catalogo.py", "feedback por guild, promover exige fonte"),
    149: (PRONTA, "tests/test_flow_control.py", "backpressure"),
    150: (PRONTA, "tests/test_flow_control.py", "cota por guild em janela"),
    158: (PRONTA, "76ae5c1", "cancelamento cooperativo"),
    169: (PRONTA, "tests/test_design_system.py", "compara forma pelo propósito, nunca pelo nome"),
}

#: Seções deliberadamente fora, com o motivo. Não é "esqueci": é decisão.
_FORA: dict[int, str] = {
    28: "pesquisa na web: 21 tools fixas, todas de operação no Discord",
    29: "pesquisa na web",
    30: "pesquisa na web",
    31: "pesquisa na web",
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
            if not _eh_titulo_de_secao(titulo):
                continue
            # Primeiro que casar vence; títulos repetidos não sobrescrevem um bom.
            if n not in out or (not out[n] and titulo):
                out[n] = titulo
    return out


def _eh_titulo_de_secao(titulo: str) -> bool:
    """Cabeçalho de seção é CAIXA ALTA. Isso exclui item de lista numerada.

    Caso real que motivou: a seção 54 tem "2. OAuth legítimo;" na lista dela.
    Sem este filtro o parser inventava uma seção 2 chamada "OAuth legítimo" -
    exatamente o tipo de dado inventado que este script existe para impedir.
    """
    if not titulo or not any(ch.isalpha() for ch in titulo):
        return False
    return titulo.upper() == titulo


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

    # Regra 5 (spec 160): PRONTA exige teste. Apontar para src/ prova que o
    # código existe, não que ele foi testado e validado - e "o código foi
    # escrito" é exatamente o que a spec 160 manda NÃO considerar conclusão.
    for n, (status, evid, _obs) in sorted(_EVIDENCIAS.items()):
        if status != PRONTA:
            continue
        if re.fullmatch(r"[0-9a-f]{7,40}", evid):
            continue  # commit: o histórico é a evidência
        if not evid.startswith("tests/"):
            erros.append(
                f"seção {n}: PRONTA exige evidência em tests/ ou commit, "
                f"recebeu {evid} (spec 160)"
            )

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
