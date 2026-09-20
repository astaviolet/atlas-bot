"""Contadores de uso do pool, para o painel interno e para o log de auditoria.

Nada aqui guarda conteudo de conversa nem credencial: so numeros e nomes de
rota. O objetivo e responder "onde a capacidade esta sendo gasta e o que esta
falhando", nao inspecionar pedido de usuario.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from typing import Any


class PoolStats:
    """Contadores agregados + por rota. Seguro para uso concorrente."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.iniciado_em = time.time()
        self.requests = 0
        self.successes = 0
        self.failures = 0
        self.fallbacks = 0          # quantas vezes trocou de rota no meio de um pedido
        self.retries = 0            # tentativas repetidas na mesma rota
        self.rate_limited = 0       # 429/503 recebidos
        self.timeouts = 0
        self.cache_hits = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self._latencia: list[float] = []
        self._por_rota: Counter[str] = Counter()
        self._erros_por_tipo: Counter[str] = Counter()
        self._ultima_rota_ok: str | None = None

    # ---------------------------------------------------------------- registro
    def request(self) -> None:
        with self._lock:
            self.requests += 1

    def success(self, route: str, *, latency_ms: float, usage: dict | None = None) -> None:
        with self._lock:
            self.successes += 1
            self._por_rota[route] += 1
            self._ultima_rota_ok = route
            self._latencia.append(latency_ms)
            if len(self._latencia) > 500:      # janela movel, nao cresce para sempre
                self._latencia = self._latencia[-500:]
            if usage:
                self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
                self.completion_tokens += int(usage.get("completion_tokens") or 0)

    def failure(self, route: str, *, kind: str) -> None:
        with self._lock:
            self.failures += 1
            self._erros_por_tipo[kind] += 1
            if kind == "rate_limit":
                self.rate_limited += 1
            elif kind == "timeout":
                self.timeouts += 1

    def fallback(self) -> None:
        with self._lock:
            self.fallbacks += 1

    def retry(self) -> None:
        with self._lock:
            self.retries += 1

    def cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    # ------------------------------------------------------------------- leitura
    def _percentil(self, ordenado: list[float], p: float) -> float | None:
        if not ordenado:
            return None
        i = min(len(ordenado) - 1, int(round(p * (len(ordenado) - 1))))
        return round(ordenado[i], 1)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            ordenado = sorted(self._latencia)
            total = self.successes + self.failures
            return {
                "uptime_s": round(time.time() - self.iniciado_em, 1),
                "requests": self.requests,
                "sucessos": self.successes,
                "falhas": self.failures,
                "taxa_erro": round(self.failures / total, 3) if total else 0.0,
                "fallbacks": self.fallbacks,
                "retries": self.retries,
                "rate_limited": self.rate_limited,
                "timeouts": self.timeouts,
                "cache_hits": self.cache_hits,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "latencia_p50_ms": self._percentil(ordenado, 0.50),
                "latencia_p95_ms": self._percentil(ordenado, 0.95),
                "por_rota": dict(self._por_rota.most_common()),
                "erros_por_tipo": dict(self._erros_por_tipo.most_common()),
                "ultima_rota_ok": self._ultima_rota_ok,
            }


def formatar_painel(stats: PoolStats, health: dict[str, dict], catalogo: dict) -> str:
    """Painel de texto para `main.py --health`. So numeros e nomes de rota."""
    s = stats.snapshot()
    linhas = [
        "POOL DE IA",
        f"  gateways {catalogo['gateways']} | rotas {catalogo['rotas']} | "
        f"sem chave {catalogo['sem_chave']} | com tool calling {catalogo['com_tool_calling']}",
        "",
        "USO",
        f"  requests {s['requests']} | sucessos {s['sucessos']} | falhas {s['falhas']} "
        f"| taxa de erro {s['taxa_erro']:.1%}",
        f"  fallbacks {s['fallbacks']} | retries {s['retries']} | "
        f"rate limited {s['rate_limited']} | timeouts {s['timeouts']}",
        f"  latencia p50 {s['latencia_p50_ms']} ms | p95 {s['latencia_p95_ms']} ms",
        f"  tokens: {s['prompt_tokens']} entrada / {s['completion_tokens']} saida",
        f"  cache hits: {s['cache_hits']}",
        "",
        "SAUDE DAS ROTAS",
    ]
    if not health:
        linhas.append("  (nenhuma rota usada ainda)")
    for rota, h in sorted(health.items()):
        lat = f"{h['latencia_ema_ms']}ms" if h["latencia_ema_ms"] else "-"
        linhas.append(
            f"  {h['estado']:<10} {rota:<52} ok={h['sucessos']:<3} err={h['falhas']:<3} {lat}"
        )
        if h["ultimo_erro"]:
            linhas.append(f"             ultimo erro: {h['ultimo_erro'][:70]}")
        if h["cooldown_restante_s"]:
            linhas.append(f"             cooldown: {h['cooldown_restante_s']}s")
    return "\n".join(linhas)
