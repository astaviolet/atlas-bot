"""Alertas (spec 122).

O painel (`observability.formatar_painel_geral`) responde "como está o sistema?"
quando alguém pergunta. Alerta é o contrário: o sistema fala sozinho quando algo
passa do limite.

O QUE ESTE MÓDULO É
-------------------
Puro e determinístico. Recebe estado já medido — resumo de auditoria, saúde do
pool, tamanho de fila, tarefas — e devolve alertas. Não consulta nada, não envia
nada, não decide nada. Quem decide o que fazer com o alerta é quem chama.

POR QUE TEM COOLDOWN
--------------------
Spec 122 lista "falhas repetidas" como gatilho. Sem cooldown, uma taxa de erro
alta dispara o mesmo alerta em toda avaliação — o que transforma o sistema de
alerta em spam, que é exatamente o comportamento que a spec 17 proíbe no bot.
O cooldown é por código de alerta: o problema continua visível, só não repete.

POR QUE OS LIMIARES SÃO EXPLÍCITOS E INJETÁVEIS
-----------------------------------------------
Número mágico escondido em condição é limiar que ninguém consegue ajustar nem
testar. Tudo aqui vem de `LimitesDeAlerta`, com default conservador: é melhor um
alerta tardio do que um alerta falso que treina todo mundo a ignorar o sistema.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class Severidade(str, Enum):
    INFO = "info"
    AVISO = "aviso"
    CRITICO = "critico"


#: Ordem de gravidade. Maior = mais grave.
_ORDEM = {Severidade.INFO: 0, Severidade.AVISO: 1, Severidade.CRITICO: 2}


@dataclass(frozen=True)
class Alerta:
    codigo: str
    severidade: Severidade
    mensagem: str
    #: Número bruto que disparou. Sem isto o alerta é opinião, não medição.
    valor: float | None = None
    limite: float | None = None


@dataclass(frozen=True)
class LimitesDeAlerta:
    """Limiares. Conservadores de propósito (ver docstring do módulo)."""

    #: Fração de ações com erro sobre o total.
    taxa_erro_aviso: float = 0.20
    taxa_erro_critico: float = 0.50
    #: Quantidade mínima de ações para a taxa significar alguma coisa. Com 2
    #: ações e 1 erro a "taxa" é 50% e não quer dizer nada.
    minimo_para_taxa: int = 10
    #: Rotas do pool indisponíveis.
    rotas_fora_aviso: int = 1
    #: Fração do pool fora do ar.
    pool_fora_critico: float = 0.75
    #: Tamanho de fila que já é acúmulo.
    fila_acumulada: int = 25
    #: Tarefas que não terminaram dentro do prazo.
    tarefas_presas: int = 1
    #: Respostas 429 na janela. Um 429 isolado é rotina de provedor gratuito;
    #: vários seguidos significa que o pool está sendo empurrado além do limite.
    rate_limited_aviso: int = 3
    #: Segundos sem cooldown entre alertas do mesmo código.
    cooldown_segundos: float = 300.0


def _taxa_erro(resumo: dict[str, Any] | None) -> tuple[float, int] | None:
    """Fração de erro e total de ações. None se não há dado suficiente."""
    if not isinstance(resumo, dict):
        return None
    por_resultado = resumo.get("por_resultado")
    if not isinstance(por_resultado, dict):
        return None
    try:
        total = sum(int(v) for v in por_resultado.values())
        ok = int(por_resultado.get("ok", 0))
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    return (total - ok) / total, total


def avaliar(
    *,
    resumo: dict[str, Any] | None = None,
    ai: dict[str, Any] | None = None,
    fila: int | None = None,
    tarefas_presas: int | None = None,
    rate_limited: int | None = None,
    limites: LimitesDeAlerta | None = None,
) -> list[Alerta]:
    """Avalia o estado e devolve alertas, do mais grave para o mais leve.

    Cada entrada é opcional de propósito: quem chama passa só o que tem medido.
    Ausência de dado nunca vira alerta — vira silêncio. Inventar alerta a partir
    de dado ausente seria falso positivo.
    """
    lim = limites or LimitesDeAlerta()
    saida: list[Alerta] = []

    # ---- erro elevado
    taxa = _taxa_erro(resumo)
    if taxa is not None:
        fracao, total = taxa
        if total >= lim.minimo_para_taxa:
            if fracao >= lim.taxa_erro_critico:
                saida.append(Alerta(
                    "erro_elevado", Severidade.CRITICO,
                    f"{fracao:.0%} das ações estão falhando ({total} ações avaliadas)",
                    valor=round(fracao, 3), limite=lim.taxa_erro_critico,
                ))
            elif fracao >= lim.taxa_erro_aviso:
                saida.append(Alerta(
                    "erro_elevado", Severidade.AVISO,
                    f"{fracao:.0%} das ações estão falhando ({total} ações avaliadas)",
                    valor=round(fracao, 3), limite=lim.taxa_erro_aviso,
                ))

    # ---- provider down / pool degradado
    if isinstance(ai, dict):
        fora = ai.get("rotas_fora")
        total_rotas = ai.get("total_rotas")
        try:
            fora_n = int(fora) if fora is not None else 0
            total_n = int(total_rotas) if total_rotas is not None else 0
        except (TypeError, ValueError):
            fora_n = total_n = 0
        if total_n > 0 and fora_n >= lim.rotas_fora_aviso:
            fracao_fora = fora_n / total_n
            if fracao_fora >= lim.pool_fora_critico:
                saida.append(Alerta(
                    "pool_fora", Severidade.CRITICO,
                    f"{fora_n} de {total_n} rotas de IA fora do ar",
                    valor=float(fora_n), limite=float(total_n),
                ))
            else:
                saida.append(Alerta(
                    "pool_degradado", Severidade.AVISO,
                    f"{fora_n} de {total_n} rotas de IA fora do ar",
                    valor=float(fora_n), limite=float(total_n),
                ))

    # ---- fila acumulada
    if fila is not None:
        try:
            fila_n = int(fila)
        except (TypeError, ValueError):
            fila_n = 0
        if fila_n >= lim.fila_acumulada:
            saida.append(Alerta(
                "fila_acumulada", Severidade.AVISO,
                f"{fila_n} ações aguardando na fila",
                valor=float(fila_n), limite=float(lim.fila_acumulada),
            ))

    # ---- tarefas presas
    if tarefas_presas is not None:
        try:
            presas = int(tarefas_presas)
        except (TypeError, ValueError):
            presas = 0
        if presas >= lim.tarefas_presas:
            saida.append(Alerta(
                "tarefas_presas", Severidade.CRITICO,
                f"{presas} tarefa(s) não terminaram dentro do prazo",
                valor=float(presas), limite=float(lim.tarefas_presas),
            ))

    # ---- rate limit (429). Spec 122 lista explicitamente.
    if rate_limited is not None:
        try:
            rl = int(rate_limited)
        except (TypeError, ValueError):
            rl = 0
        if rl >= lim.rate_limited_aviso:
            saida.append(Alerta(
                "rate_limited", Severidade.AVISO,
                f"{rl} respostas de limite de taxa na janela",
                valor=float(rl), limite=float(lim.rate_limited_aviso),
            ))

    saida.sort(key=lambda a: -_ORDEM[a.severidade])
    return saida


class ControladorDeAlerta:
    """Aplica cooldown para o mesmo alerta não virar spam.

    O estado é por código de alerta, não por mensagem: se o número muda mas o
    problema é o mesmo, ainda é o mesmo alerta.
    """

    def __init__(
        self,
        *,
        cooldown_segundos: float = LimitesDeAlerta().cooldown_segundos,
        clock: Callable[[], float] | None = None,
    ) -> None:
        import time as _time

        self.cooldown = float(cooldown_segundos)
        self._clock = clock or _time.monotonic
        self._ultimo: dict[str, float] = {}

    def novos(self, alertas: list[Alerta]) -> list[Alerta]:
        """Filtra os que ainda estão em cooldown. Não muta a lista recebida.

        NAO marca cooldown. Marcar aqui tornaria `registrar_envio` decorativo: um
        envio que falha ja teria silenciado o alerta, e o problema sumiria sem
        ninguem ter sido avisado. Quem entrega chama `registrar_envio`.
        """
        agora = self._clock()
        return [
            a for a in alertas
            if (visto := self._ultimo.get(a.codigo)) is None
            or (agora - visto) >= self.cooldown
        ]

    def registrar_envio(self, alertas: list[Alerta]) -> None:
        """Marca como enviados. Separado de `novos` para o caso de o envio
        falhar: aí o alerta não foi entregue e não deve entrar em cooldown."""
        agora = self._clock()
        for a in alertas:
            self._ultimo[a.codigo] = agora

    def rearmar(self, codigo: str) -> None:
        """Tira do cooldown. Usado quando o problema some e volta: o segundo
        episódio merece alerta mesmo dentro da janela do primeiro."""
        self._ultimo.pop(codigo, None)
