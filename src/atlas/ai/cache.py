"""Cache e deduplicacao de pedidos.

Regra dura da missao: nunca misturar contexto entre usuarios ou servidores.
Por isso a chave do cache SEMPRE inclui guild_id, e qualquer mutacao no
servidor invalida o cache daquele guild inteiro.

O que este cache faz de proposito e pouco:
  - deduplica pedidos identicos dentro de uma janela curta (usuario que
    mandou a mesma frase duas vezes, ou cliente que reenviou);
  - economiza token quando a resposta ainda e valida.

O que ele NAO faz: cachear resposta de pedido que mudou o servidor. Depois de
mutacao o estado e outro, entao a resposta anterior nao serve mais.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


def chave_pedido(
    *,
    guild_id: int,
    system: str,
    history: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> str:
    """Identificador estavel de um pedido, isolado por servidor.

    guild_id entra primeiro de proposito: mesmo texto em servidores diferentes
    nunca pode colidir.
    """
    material = json.dumps(
        {"g": int(guild_id), "s": system, "h": history, "t": [t.get("function", {}).get("name") for t in tools]},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()


@dataclass
class CacheEntry:
    value: Any
    expira_em: float


class RequestCache:
    """Cache com TTL, particionado por guild, com invalidacao por mutacao."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 20.0,
        max_entries: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._store: dict[str, CacheEntry] = {}
        # guarda qual chave pertence a qual guild, para invalidar por servidor
        self._por_guild: dict[int, set[str]] = {}
        self.hits = 0
        self.misses = 0
        self.invalidations = 0

    def get(self, guild_id: int, chave: str) -> Any | None:
        now = self._clock()
        with self._lock:
            entrada = self._store.get(chave)
            if entrada is None:
                self.misses += 1
                return None
            if now >= entrada.expira_em:
                self._remover(chave, guild_id)
                self.misses += 1
                return None
            self.hits += 1
            return entrada.value

    def put(self, guild_id: int, chave: str, value: Any) -> None:
        now = self._clock()
        with self._lock:
            if len(self._store) >= self.max_entries:
                self._podar(now)
            self._store[chave] = CacheEntry(value=value, expira_em=now + self.ttl_seconds)
            self._por_guild.setdefault(int(guild_id), set()).add(chave)

    def invalidate_guild(self, guild_id: int) -> int:
        """Descarta tudo de um servidor. Chamado depois de qualquer mutacao."""
        with self._lock:
            chaves = self._por_guild.pop(int(guild_id), set())
            for chave in chaves:
                self._store.pop(chave, None)
            if chaves:
                self.invalidations += 1
            return len(chaves)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._por_guild.clear()

    # ---------------------------------------------------------------- internos
    def _remover(self, chave: str, guild_id: int) -> None:
        self._store.pop(chave, None)
        grupo = self._por_guild.get(int(guild_id))
        if grupo:
            grupo.discard(chave)

    def _podar(self, now: float) -> None:
        """Remove expirados; se ainda estiver cheio, derruba o mais antigo."""
        expiradas = [k for k, v in self._store.items() if now >= v.expira_em]
        for k in expiradas:
            self._store.pop(k, None)
        if len(self._store) >= self.max_entries and self._store:
            mais_antiga = min(self._store.items(), key=lambda kv: kv[1].expira_em)[0]
            self._store.pop(mais_antiga, None)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "entradas": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
                "invalidacoes": self.invalidations,
            }
