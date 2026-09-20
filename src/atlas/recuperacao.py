"""Recuperação após restart (spec 93).

O QUE A SPEC EXIGE
------------------
Se o processo reiniciar no meio de uma tarefa: detectar as tarefas incompletas,
**nunca executar novamente às cegas**, consultar o estado real, e retomar ou
marcar como interrompida.

POR QUE "NUNCA ÀS CEGAS" É A PARTE IMPORTANTE
---------------------------------------------
Reexecutar um plano depois de restart parece inofensivo até lembrar que criar
canal não é idempotente por natureza: a Fase 3 reusa por nome, então na maioria
dos casos não duplica — mas `edit_role`, `set_channel_permissions` e
`reorder_channels` aplicados duas vezes podem sobrescrever o que um humano
ajustou no meio. E exclusão reexecutada apaga o que foi recriado depois.

Então esta camada **não executa nada**. Ela compara a intenção registrada com o
estado real e devolve um relatório classificando cada ação. Quem decide retomar
é o usuário, com o relatório na frente.

ONDE ISTO VALE DE VERDADE
-------------------------
No Actions o filesystem é efêmero, então o registro não sobrevive à run e a
recuperação quase nunca tem o que achar. Isso não torna o código morto: ele roda
em qualquer deploy com disco persistente (processo local, container com volume),
e o teste cobre o caminho completo. Está anotado aqui em vez de ser apresentado
como garantia que não existe (spec 185).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Ferramentas cujo efeito dá para conferir olhando o estado real.
_VERIFICAVEIS = {
    "create_channel", "create_category", "create_role",
    "delete_channel", "delete_category", "delete_role",
}


class RegistrarTarefas:
    """Grava a intenção ANTES de executar, para o restart ter o que comparar."""

    def __init__(self, raiz: str | Path = "logs/tarefas") -> None:
        self.raiz = Path(raiz)

    def _caminho(self, guild_id: int) -> Path:
        return self.raiz / f"{int(guild_id)}.jsonl"

    def abrir(self, guild_id: int, *, token: str, acoes: list[dict[str, Any]]) -> None:
        try:
            self.raiz.mkdir(parents=True, exist_ok=True)
            registro = {
                "token": token,
                "aberta_em": time.time(),
                "guild_id": int(guild_id),
                "acoes": acoes,
                "fechada": False,
            }
            with self._caminho(guild_id).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 - diagnostico nunca impede a operacao
            log.warning("nao deu para registrar a tarefa do guild %s", guild_id, exc_info=True)

    def fechar(self, guild_id: int, token: str) -> None:
        """Marca como concluída. Reescreve o arquivo: tarefa fechada não é
        candidata a recuperação."""
        caminho = self._caminho(guild_id)
        if not caminho.exists():
            return
        linhas = []
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if not linha.strip():
                continue
            try:
                reg = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if reg.get("token") == token:
                reg["fechada"] = True
            linhas.append(json.dumps(reg, ensure_ascii=False))
        try:
            caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        except Exception:  # noqa: BLE001
            log.warning("nao deu para fechar a tarefa %s", token, exc_info=True)

    def pendentes(self, guild_id: int) -> list[dict[str, Any]]:
        caminho = self._caminho(guild_id)
        if not caminho.exists():
            return []
        saida = []
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if not linha.strip():
                continue
            try:
                reg = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if not reg.get("fechada"):
                saida.append(reg)
        return saida


def avaliar_reinicio(
    tarefa: dict[str, Any], snapshot: Any
) -> dict[str, Any]:
    """Compara a intenção com o estado real. Não executa nada.

    Cada ação vira um destes três:
    - `ja_feito`     — o estado real já reflete a ação (não repetir).
    - `faltando`     — o estado real não reflete; candidata a retomar.
    - `impossivel`   — não dá para conferir pelo estado (edit/set/move). Estas
                       NUNCA são retomadas automaticamente: aplicar duas vezes
                       pode sobrescrever ajuste humano feito no meio.
    """
    canais = {c.name.strip().casefold(): c for c in getattr(snapshot, "channels", [])}
    cargos = {r.name.strip().casefold(): r for r in getattr(snapshot, "roles", [])}

    classificados: dict[str, list[dict[str, Any]]] = {
        "ja_feito": [], "faltando": [], "impossivel": [],
    }

    for acao in tarefa.get("acoes") or []:
        tool = str(acao.get("tool") or acao.get("name") or "")
        params = acao.get("params") or acao.get("args") or {}
        nome = str(params.get("name") or "").strip().casefold()
        item = {"tool": tool, "nome": params.get("name")}

        if tool not in _VERIFICAVEIS:
            classificados["impossivel"].append(item)
            continue

        alvo = canais if tool.endswith(("channel", "category")) else cargos
        existe = bool(nome) and nome in alvo

        if tool.startswith("create"):
            classificados["ja_feito" if existe else "faltando"].append(item)
        elif tool.startswith("delete"):
            # se ainda existe, a exclusao nao aconteceu
            classificados["faltando" if existe else "ja_feito"].append(item)
        else:
            classificados["impossivel"].append(item)

    return {
        "token": tarefa.get("token"),
        "aberta_em": tarefa.get("aberta_em"),
        **classificados,
        "retomavel": bool(classificados["faltando"]) and not classificados["impossivel"],
    }


def relatorio_de_reinicio(
    avaliacao: dict[str, Any], nome_servidor: str = ""
) -> str:
    """Texto para o usuário decidir. Sem executar nada por conta própria."""
    feitos = len(avaliacao.get("ja_feito") or [])
    faltam = len(avaliacao.get("faltando") or [])
    incertos = len(avaliacao.get("impossivel") or [])

    partes = [f"Encontrei uma tarefa interrompida{f' em {nome_servidor}' if nome_servidor else ''}."]
    partes.append(f"{feitos} ação(ões) já estavam feitas, {faltam} não foram.")
    if incertos:
        partes.append(
            f"{incertos} eu não consigo conferir pelo estado do servidor, "
            "e não vou repetir às cegas — pode sobrescrever algo que alguém ajustou."
        )
    if avaliacao.get("retomavel"):
        partes.append("Se quiser, me pede de novo que eu completo o que falta.")
    else:
        partes.append("Me diz o que você quer fazer com o que falta.")
    return " ".join(partes)
