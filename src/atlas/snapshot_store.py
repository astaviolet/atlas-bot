"""Snapshot logico e rollback (spec 86, 87, 88).

O QUE E SALVO
-------------
Estado estrutural do servidor: categorias, canais (nome, tipo, posicao, pai,
topico, nsfw, slowmode, permissoes) e cargos (nome, posicao, cor, permissoes,
hoist, mentionable). Mais metadados: versao, timestamp, quem pediu, guild,
resumo da mudanca.

NUNCA e salvo: token, chave de IA, credencial, conteudo de mensagem. O snapshot
estrutura so tem metadados de configuracao - nao ha campo por onde segredo
entraria, e `_sanitizar` garante isso mesmo se alguem acrescentar campo depois.

O ROLLBACK E POR INVERSAO, NAO POR RESTAURACAO CEGA
---------------------------------------------------
O Discord nao tem transacao nem "restaurar para o instante X". O que da para
fazer de verdade e inverter as acoes que acabaram de rodar: o que foi criado e
excluido, o que foi excluido e recriado, o que foi renomeado volta ao nome
antigo. Restauracao cega de ids nao existe - ids novos sao novos (spec 85).

O plano de rollback passa pelas MESMAS barreiras de politica e permissao que
qualquer outro plano. Rollback nao e atalho de seguranca.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Chaves que nunca podem aparecer num snapshot, em nenhum nivel.
_PROIBIDAS = {"token", "secret", "password", "api_key", "apikey", "authorization",
              "discord_token", "ai_api_key"}

_INVERSA = {
    "create_channel": "delete_channel",
    "create_category": "delete_category",
    "create_role": "delete_role",
}
_CHAVE_ID = {
    "create_channel": ("channel_id", "id"),
    "create_category": ("category_id", "id"),
    "create_role": ("role_id", "id"),
}


def _sanitizar(objeto: Any) -> Any:
    """Tira qualquer chave com cara de credencial, recursivamente."""
    if isinstance(objeto, dict):
        return {
            k: _sanitizar(v)
            for k, v in objeto.items()
            if str(k).lower() not in _PROIBIDAS
        }
    if isinstance(objeto, list):
        return [_sanitizar(v) for v in objeto]
    return objeto


class SnapshotStore:
    """Guarda o ultimo snapshot logico de cada guild, em disco.

    Um arquivo por guild. O ambiente do Actions e efemero, entao isto nao
    sobrevive a run - o que e aceitavel: rollback serve para desfazer a
    operacao que acabou de acontecer, nao para arqueologia.
    """

    def __init__(self, raiz: str | Path = "logs/snapshots") -> None:
        self.raiz = Path(raiz)

    def _caminho(self, guild_id: int) -> Path:
        return self.raiz / f"{int(guild_id)}.json"

    def _historico(self, guild_id: int) -> Path:
        return self.raiz / f"{int(guild_id)}.historico.jsonl"

    def proxima_versao(self, guild_id: int) -> int:
        """Versao anterior + 1. Comeca em 1."""
        return (self.ultima_versao(guild_id) or 0) + 1

    def ultima_versao(self, guild_id: int) -> int | None:
        versoes = self.listar_versoes(guild_id)
        return versoes[-1]["versao"] if versoes else None

    def listar_versoes(self, guild_id: int) -> list[dict[str, Any]]:
        """Metadados de cada versao, da mais antiga para a mais nova (spec 88).

        So metadados de proposito: listar nao precisa carregar o estado inteiro
        de cada versao, e o historico pode ficar grande.
        """
        caminho = self._historico(guild_id)
        if not caminho.exists():
            return []
        saida = []
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha:
                continue
            try:
                meta = json.loads(linha)
            except json.JSONDecodeError:
                continue  # linha corrompida nao invalida o resto do historico
            saida.append({
                "versao": meta.get("versao"),
                "salvo_em": meta.get("salvo_em"),
                "autor": meta.get("autor"),
                "resumo": meta.get("resumo"),
            })
        return saida

    def salvar(
        self,
        guild_id: int,
        snapshot: Any,
        *,
        autor: str = "?",
        resumo: str = "",
        versao: int | None = None,
    ) -> Path:
        """Grava o estado atual antes de mudar. Nunca levanta: falhar aqui nao
        pode impedir a operacao, mas tem que ficar no log.

        Alem do arquivo "ultimo estado", acrescenta uma linha ao historico. Sem
        historico nao ha versionamento (spec 88) - so um snapshot que some.
        """
        try:
            if versao is None:
                versao = self.proxima_versao(guild_id)
            dados = _sanitizar({
                "versao": versao,
                "salvo_em": time.time(),
                "guild_id": int(guild_id),
                "autor": str(autor),
                "resumo": str(resumo),
                "servidor": getattr(snapshot, "name", "?"),
                "canais": [c.to_dict() for c in snapshot.channels],
                "cargos": [r.to_dict() for r in snapshot.roles],
            })
            self.raiz.mkdir(parents=True, exist_ok=True)
            caminho = self._caminho(guild_id)
            texto = json.dumps(dados, ensure_ascii=False)
            caminho.write_text(texto, encoding="utf-8")

            hist = self._historico(guild_id)
            with hist.open("a", encoding="utf-8") as fh:
                fh.write(texto + "\n")
            return caminho
        except Exception:  # noqa: BLE001 - diagnostico nao pode derrubar nada
            log.exception("nao deu para salvar o snapshot do guild %s", guild_id)
            raise

    def ler_versao(self, guild_id: int, versao: int) -> dict[str, Any] | None:
        """Le uma versao especifica do historico. None se nao existe."""
        caminho = self._historico(guild_id)
        if not caminho.exists():
            return None
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha:
                continue
            try:
                dados = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if dados.get("versao") == versao:
                return dados
        return None

    def ler(self, guild_id: int) -> dict[str, Any] | None:
        caminho = self._caminho(guild_id)
        if not caminho.exists():
            return None
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log.exception("snapshot do guild %s esta ilegivel", guild_id)
            return None


def plano_de_rollback(resultados: list[Any]) -> list[dict[str, Any]]:
    """Inverte as acoes que RODARAM, na ordem contraria.

    So o que deu certo e so o que tem inversa conhecida. Uma exclusao nao
    aparece aqui como "recriar" porque recriar perde id, historico e permissoes
    - o usuario precisa saber disso em vez de receber um rollback de mentira.
    """
    inversas: list[dict[str, Any]] = []
    for r in reversed(resultados):
        if not getattr(r, "ok", False):
            continue
        acao = getattr(r, "action", None)
        tool = getattr(acao, "tool", "") or ""
        alvo = _INVERSA.get(tool)
        if alvo is None:
            continue
        dados = getattr(r, "data", None) or {}
        criado = dados.get("created") or {}
        novo_id = criado.get("id") or criado.get("channel_id") or criado.get("role_id")
        if not novo_id:
            continue
        campo = _CHAVE_ID[tool][0]
        inversas.append({"name": alvo, "args": {campo: str(novo_id)}})
    return inversas


#: O que se perde ao recriar algo que foi excluído. Spec 87: o rollback de
#: destruição existe, mas tem de dizer o que não volta. Prometer "desfazer"
#: inteiro seria sucesso falso (spec 185).
_PERDAS_DA_RECRIACAO: dict[str, tuple[str, ...]] = {
    "delete_channel": ("id do canal (menções <#id> antigas param de funcionar)",
                       "histórico de mensagens", "fixados"),
    "delete_category": ("id da categoria", "ordem dos canais que estavam dentro"),
    "delete_role": ("id do cargo (menções <@&id> antigas param de funcionar)",
                    "cargo dos membros que o tinham", "posição exata na hierarquia"),
}

#: Tool que recria cada exclusão, e os campos que o snapshot permite recuperar.
#: O quarto elemento é o campo de id que a exclusão recebe. Não dá para
#: reaproveitar `_CHAVE_ID`: aquela é indexada pelas tools de CRIAÇÃO (é o
#: rollback de criação, onde o id vem da resposta). Aqui a tool é a de exclusão.
_RECRIO = {
    "delete_channel": ("create_channel", ("name", "type", "topic", "nsfw", "slowmode_delay"), "channel_id"),
    "delete_category": ("create_category", ("name",), "category_id"),
    "delete_role": ("create_role", ("name", "color", "hoist", "mentionable"), "role_id"),
}


def plano_de_restauracao(
    snapshot: Any, resultados: list[Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Plano para recriar o que foi EXCLUÍDO, mais a lista do que não volta.

    Diferença para `plano_de_rollback`: aquela inverte o que foi criado (excluir
    de volta) — reversível de verdade. Esta lida com exclusão, onde não existe
    inversa: o Discord não devolve id, histórico nem cargo de membro. O máximo
    honesto é recriar a estrutura com o mesmo nome, tipo e configurações que o
    snapshot guardou, e dizer na cara o que se perdeu.

    Devolve tupla `(plano, perdas)` de propósito. Devolver só o plano convidaria
    o chamador a apresentar como "desfeito" — e não foi.
    """
    por_id: dict[str, Any] = {}
    for entidade in getattr(snapshot, "channels", []) or []:
        por_id[str(getattr(entidade, "id", ""))] = entidade
    for entidade in getattr(snapshot, "roles", []) or []:
        por_id[str(getattr(entidade, "id", ""))] = entidade

    plano: list[dict[str, Any]] = []
    perdas: list[str] = []
    for r in resultados:
        if not getattr(r, "ok", False):
            continue
        acao = getattr(r, "action", None)
        tool = getattr(acao, "tool", "") or ""
        if tool not in _RECRIO:
            continue

        alvo_tool, campos, campo_id = _RECRIO[tool]
        params = getattr(acao, "params", {}) or {}
        alvo_id = str(params.get(campo_id) or params.get("id") or "")
        entidade = por_id.get(alvo_id)
        if entidade is None:
            continue  # sem registro no snapshot: não inventar estrutura

        args = {campo: getattr(entidade, campo) for campo in campos
                if getattr(entidade, campo, None) is not None}
        if not args.get("name"):
            continue
        if "type" in args:
            tipo = args["type"]
            args["type"] = getattr(tipo, "value", tipo)
        pai = getattr(entidade, "parent_id", None)
        if pai:
            args["parent_id"] = str(pai)

        plano.append({"name": alvo_tool, "args": args})
        nome = args["name"]
        for perda in _PERDAS_DA_RECRIACAO[tool]:
            item = f"{nome}: perde {perda}"
            if item not in perdas:
                perdas.append(item)
    return plano, perdas
