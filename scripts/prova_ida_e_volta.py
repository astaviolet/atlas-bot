"""Prova de ida e volta contra o bot que esta no GitHub Actions.

Diferente de `verifica_ponta_a_ponta.py` (que liga um cliente local), aqui
NINGUEM liga o agente: so mandamos a mensagem mencionando o bot e esperamos
ELE responder. Se responder, o processo hospedado esta vivo e de ponta a ponta.

Uso:  .venv/bin/python scripts/prova_ida_e_volta.py "pedido aqui"
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

API = "https://discord.com/api/v10"
BOT_ID = 1550239353802858626
CANAL = 1551015583712026768
TEMPO_MAX = 120


def req(metodo: str, caminho: str, corpo: dict | None = None) -> tuple[int, object]:
    dados = json.dumps(corpo).encode() if corpo is not None else None
    r = urllib.request.Request(
        f"{API}{caminho}",
        data=dados,
        method=metodo,
        headers={
            "Authorization": f"Bot {TOKEN}",
            "User-Agent": "DiscordBot (atlas-prova, 1.0)",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


load_dotenv()
TOKEN = os.environ["DISCORD_TOKEN"]
pedido = sys.argv[1] if len(sys.argv) > 1 else "quantos canais tem esse servidor?"

st, antes = req("GET", f"/channels/{CANAL}/messages?limit=1")
if st != 200:
    print(f"FALHA ao ler o canal: HTTP {st} {antes}")
    raise SystemExit(1)
marco = antes[0]["id"] if antes else "0"
print(f"pedido      : {pedido!r}")
print(f"mensagem    : id de referencia {marco}")

st, enviado = req(
    "POST",
    f"/channels/{CANAL}/messages",
    {"content": f"<@{BOT_ID}> {pedido}"},
)
print(f"enviada     : HTTP {st}")
if st not in (200, 201):
    raise SystemExit(1)
# O pedido e postado com o proprio token do bot, entao a author dele tambem e
# o bot. Sem ignorar esse id a "resposta" encontrada seria o nosso envio.
id_pedido = str(enviado["id"])
print(f"id do pedido: {id_pedido} (ignorado na busca da resposta)")

comeco = time.monotonic()
while time.monotonic() - comeco < TEMPO_MAX:
    time.sleep(3)
    st, msgs = req("GET", f"/channels/{CANAL}/messages?limit=15&after={marco}")
    if st != 200:
        continue
    respostas = [
        m
        for m in msgs
        if m["author"]["id"] == str(BOT_ID) and m["id"] != id_pedido
    ]
    if respostas:
        m = sorted(respostas, key=lambda x: x["id"])[0]
        espera = time.monotonic() - comeco
        flags = m.get("flags", 0)
        comp = m.get("components") or []
        print(f"\nRESPOSTA DO BOT em {espera:.1f}s")
        print(f"  mensagens dele : {len(respostas)} (deve ser 1)")
        print(f"  components_v2  : {bool(flags & 32768)} (flags={flags})")
        print(f"  embeds         : {len(m.get('embeds') or [])}")
        if comp:
            for c in comp[0].get("components", []):
                for sub in c.get("components", []):
                    texto = sub.get("content", "")
                    if texto:
                        print(f"  texto          : {texto!r}")
        if not m.get("embeds") and not (m.get("flags", 0) & 32768):
            print(f"  CONTEUDO CRUDO : {m.get('content')!r}")
        raise SystemExit(0 if len(respostas) == 1 else 1)
    print(f"  ...{time.monotonic() - comeco:.0f}s esperando")

print(f"\nFALHA: o bot nao respondeu em {TEMPO_MAX}s")
raise SystemExit(1)
