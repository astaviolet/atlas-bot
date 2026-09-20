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

    def salvar(
        self,
        guild_id: int,
        snapshot: Any,
        *,
        autor: str = "?",
        resumo: str = "",
        versao: int = 1,
    ) -> Path:
        """Grava o estado atual antes de mudar. Nunca levanta: falhar aqui nao
        pode impedir a operacao, mas tem que ficar no log."""
        try:
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
            caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
            return caminho
        except Exception:  # noqa: BLE001 - diagnostico nao pode derrubar nada
            log.exception("nao deu para salvar o snapshot do guild %s", guild_id)
            raise

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
