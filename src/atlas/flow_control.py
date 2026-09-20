"""Backpressure (spec 149) e fairness por guild (spec 150).

POR QUE ISTO NAO E O RATE LIMITER QUE JA EXISTE
-----------------------------------------------
`GuildRateLimiter` e um balde de rajada: diz "voce esta rapido demais AGORA".
Ele nao responde as duas perguntas que a spec faz:

- **149 (backpressure):** quando o sistema esta saturado, admitir mais trabalho
  so piora. Precisa recusar cedo, com mensagem clara, em vez de empilhar.
- **150 (fairness):** um servidor sozinho nao pode consumir o pool inteiro.
  Precisa de cota por guild em janela deslizante - nao por rajada, por volume
  acumulado. O balde recarrega em 6s; uma cota de 120 acoes/minuto nao.

Os dois vivem aqui, separados do balde, porque sao politicas diferentes: o
balde protege a API do Discord, isto protege os OUTROS usuarios do bot.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class GuildQuota:
    """Cota por guild em janela deslizante (spec 150).

    Conta acoes ADMITIDAS nos ultimos `window_seconds`. Passou do teto, o guild
    espera ate a janela liberar - nao toma o lugar de ninguem, so fica na dele.
    """

    def __init__(
        self,
        max_acoes: int,
        window_seconds: float,
        *,
        clock=time.monotonic,
    ) -> None:
        self.max_acoes = max_acoes
        self.window_seconds = window_seconds
        self._clock = clock
        self._historico: dict[int, deque[float]] = {}
        self._trava = threading.Lock()

    def _janela(self, guild_id: int) -> deque[float]:
        h = self._historico.setdefault(guild_id, deque())
        corte = self._clock() - self.window_seconds
        while h and h[0] < corte:
            h.popleft()
        return h

    def usadas(self, guild_id: int) -> int:
        with self._trava:
            return len(self._janela(guild_id))

    def restante(self, guild_id: int) -> int:
        with self._trava:
            return max(0, self.max_acoes - len(self._janela(guild_id)))

    def espera_restante(self, guild_id: int) -> float:
        """Quantos segundos ate a janela liberar pelo menos 1 acao."""
        with self._trava:
            h = self._janela(guild_id)
            if len(h) < self.max_acoes:
                return 0.0
            return max(0.0, h[0] + self.window_seconds - self._clock())

    def estourou(self, guild_id: int) -> bool:
        return self.restante(guild_id) == 0

    def admitir(self, guild_id: int, quantidade: int = 1) -> int:
        """Registra `quantidade` acoes. Devolve quantas foram admitidas.

        Admite parcial de proposito: se cabem 3 de 10, admite 3. Recusar tudo
        por causa de 7 a mais seria punir o pedido inteiro (spec 22: sucesso
        parcial e melhor que falha total).
        """
        with self._trava:
            h = self._janela(guild_id)
            cabem = max(0, self.max_acoes - len(h))
            admitidas = min(cabem, max(0, quantidade))
            agora = self._clock()
            for _ in range(admitidas):
                h.append(agora)
            return admitidas


class Backpressure:
    """Teto de trabalho admitido (spec 149).

    Dois tetos, por motivos diferentes:
    - `max_pendentes_por_guild`: um pedido so nao pode virar 500 acoes. Recusar
      ANTES de gastar volta de IA - depois que o modelo ja planejou, o custo
      esta pago.
    - `max_guilds_em_voo`: quantos servidores podem estar executando ao mesmo
      tempo. Alem disso o novo pedido recebe "estou ocupado" na hora, em vez de
      esperar em fila que ninguem ve.
    """

    def __init__(self, max_pendentes_por_guild: int, max_guilds_em_voo: int) -> None:
        self.max_pendentes_por_guild = max_pendentes_por_guild
        self.max_guilds_em_voo = max_guilds_em_voo
        self._em_voo: set[int] = set()
        self._trava = threading.Lock()

    def plano_cabe(self, quantidade: int) -> bool:
        return quantidade <= self.max_pendentes_por_guild

    def entrar(self, guild_id: int) -> bool:
        """Marca o guild como executando. False se o teto global estourou."""
        with self._trava:
            if guild_id in self._em_voo:
                return True
            if len(self._em_voo) >= self.max_guilds_em_voo:
                return False
            self._em_voo.add(guild_id)
            return True

    def sair(self, guild_id: int) -> None:
        with self._trava:
            self._em_voo.discard(guild_id)

    def em_voo(self) -> int:
        with self._trava:
            return len(self._em_voo)
