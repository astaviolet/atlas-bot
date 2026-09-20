"""Trava por guild para operacoes estruturais (spec 64, 65, 114).

POR QUE threading.Lock E NAO asyncio.Lock
-----------------------------------------
`bot.AtlasBot._process` roda cada pedido assim:

    loop.run_in_executor(None, lambda: asyncio.run(agent.handle(...)))

Ou seja: cada mensagem vai para uma THREAD do pool com um EVENT LOOP NOVO.
Um `asyncio.Lock` vive num loop; dois pedidos em loops diferentes nao se
enxergariam e a trava nao travaria nada. Pior: `_build_agent` constroi um Agent
novo por mensagem, entao uma trava guardada no Agent nasceria destrancada a cada
pedido.

A trava tem que ser de thread e viver FORA do Agent, indexada por guild_id.

O que ela protege: dois pedidos estruturais no mesmo servidor ao mesmo tempo.
Sem isto, o plano A cria uma categoria e o plano B resolve canais pelo nome
antes de ela existir - cada um leu um snapshot diferente e os dois escrevem em
cima um do outro.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class GuildLocks:
    """Uma trava por guild_id, criada sob demanda."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[int, threading.Lock] = {}

    def _lock_for(self, guild_id: int) -> threading.Lock:
        with self._guard:
            trava = self._locks.get(guild_id)
            if trava is None:
                trava = threading.Lock()
                self._locks[guild_id] = trava
            return trava

    @contextmanager
    def tentativa(self, guild_id: int, timeout: float) -> Iterator[bool]:
        """Tenta segurar a trava do guild por ate `timeout` segundos.

        Devolve True se conseguiu. Se nao, devolve False em vez de ficar
        esperando em silencio: quem chamou decide o que dizer para a pessoa.

        timeout <= 0 significa "nao espero nada".
        """
        trava = self._lock_for(guild_id)
        pegou = trava.acquire(timeout=timeout) if timeout > 0 else trava.acquire(blocking=False)
        try:
            yield pegou
        finally:
            if pegou:
                trava.release()

    def ocupada(self, guild_id: int) -> bool:
        """So diagnostico: nao bloqueia, nao reserva."""
        trava = self._lock_for(guild_id)
        if trava.acquire(blocking=False):
            trava.release()
            return False
        return True
