#!/usr/bin/env python3
"""Sonda endpoints OpenAI-compativeis candidatos a entrar no pool.

Faz o minimo de chamadas possivel: lista de modelos, uma geracao curta e uma
chamada de tool calling. Nao bombardeia endpoint nenhum - entre candidatos ha
pausa, e cada teste tem timeout curto.

Uso:
    python scripts/probe_providers.py            # sonda o catalogo
    python scripts/probe_providers.py --json     # saida para maquina
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

UA = "AtlasBot/1.0 (probe; contato via README)"

# Catalogo inicial. Tudo aqui veio de pesquisa; nada e assumido como funcional -
# o teste abaixo e que decide quem entra no pool.
CANDIDATOS = [
    {"id": "llm7", "base": "https://api.llm7.io/v1", "auth": False},
    {"id": "ovh", "base": "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1", "auth": False},
    {"id": "kilo", "base": "https://api.kilo.ai/api/gateway/v1", "auth": False},
    {"id": "opencode-zen", "base": "https://opencode.ai/zen/v1", "auth": False},
    {"id": "pollinations", "base": "https://text.pollinations.ai/openai", "auth": False},
]

TOOL = {
    "type": "function",
    "function": {
        "name": "create_channel",
        "description": "Cria um canal no servidor",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
}


def _post(url: str, corpo: dict, timeout: float = 30) -> tuple[int, dict]:
    req = urllib.request.Request(
        url, data=json.dumps(corpo).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {"error": {"message": "?"}}
    except Exception as e:
        return 0, {"error": {"message": f"{type(e).__name__}: {e}"}}


def _get(url: str, timeout: float = 20) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {"error": {"message": "?"}}
    except Exception as e:
        return 0, {"error": {"message": f"{type(e).__name__}: {e}"}}


def probe(cand: dict) -> dict:
    base = cand["base"].rstrip("/")
    out = {"id": cand["id"], "base": base, "auth_necessaria": cand["auth"]}

    code, dados = _get(f"{base}/models")
    if code != 200:
        out["status"] = "SEM_CATALOGO"
        out["detalhe"] = f"GET /models -> {code}: {str(dados)[:110]}"
        return out

    modelos = [m.get("id") for m in dados.get("data", []) if m.get("id")]
    out["modelos_listados"] = len(modelos)
    out["amostra"] = modelos[:6]

    # geracao minima: 8 tokens de resposta, prompt curto
    alvo = modelos[0] if modelos else None
    if not alvo:
        out["status"] = "SEM_MODELOS"
        return out

    t0 = time.time()
    code, dados = _post(
        f"{base}/chat/completions",
        {"model": alvo, "messages": [{"role": "user", "content": "diga ok"}], "max_tokens": 8},
    )
    out["latencia_geracao_ms"] = int((time.time() - t0) * 1000)
    if code != 200:
        out["status"] = "GERACAO_FALHOU"
        out["detalhe"] = f"{code}: {str(dados)[:110]}"
        return out
    out["geracao"] = "OK"

    # tool calling: e o que o agente precisa, entao e eliminatorio
    t0 = time.time()
    code, dados = _post(
        f"{base}/chat/completions",
        {
            "model": alvo,
            "messages": [{"role": "user", "content": "Crie um canal chamado geral"}],
            "tools": [TOOL],
        },
    )
    out["latencia_tool_ms"] = int((time.time() - t0) * 1000)
    if code != 200:
        out["status"] = "TOOL_FALHOU"
        out["detalhe"] = f"{code}: {str(dados)[:110]}"
        return out
    tc = dados.get("choices", [{}])[0].get("message", {}).get("tool_calls")
    out["tool_calling"] = bool(tc)
    out["status"] = "APTO" if tc else "SEM_TOOL_CALLING"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--pausa", type=float, default=2.0)
    args = ap.parse_args()

    resultados = []
    for cand in CANDIDATOS:
        if not args.json:
            print(f"sondando {cand['id']}...", flush=True)
        resultados.append(probe(cand))
        time.sleep(args.pausa)

    if args.json:
        print(json.dumps(resultados, indent=2, ensure_ascii=False))
        return 0

    print()
    for r in resultados:
        print(f"  {r['id']:<16} {r['status']:<18} {r.get('detalhe','')}")
        if r["status"] == "APTO":
            print(f"      modelos={r['modelos_listados']} tool={r['tool_calling']} "
                  f"lat={r['latencia_tool_ms']}ms")
    aptos = [r["id"] for r in resultados if r["status"] == "APTO"]
    print(f"\naptos: {len(aptos)} -> {aptos}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
