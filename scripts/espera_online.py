"""Espera o aviso de vida do bot hospedado aparecer no canal de controle.

Uso:
    python scripts/espera_online.py [--texto "Online."] [--depois SNOWFLAKE] [segundos]

Duas armadilhas que ja me derrubaram, tratadas aqui:

1. `after=` do Discord exige SNOWFLAKE (id de mensagem), nao texto. Passar
   "Online." como marco devolve 400 e o script espera para sempre por nada.
   Por isso o marcador de texto e outro parametro, comparado contra o conteudo.
2. O bot responde em Components V2 (`flags=32768`), entao `content` vem vazio e
   o texto esta dentro de `components`. Comparar so `content` nunca acha nada.
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


def texto_de(mensagem: dict) -> str:
    """Junta content e qualquer texto dentro de components, recursivamente."""
    partes = [mensagem.get("content") or ""]

    def andar(no):
        if isinstance(no, dict):
            if no.get("content"):
                partes.append(no["content"])
            for v in no.values():
                andar(v)
        elif isinstance(no, list):
            for v in no:
                andar(v)

    andar(mensagem.get("components") or [])
    return " ".join(p.strip() for p in partes if p.strip())


def main() -> int:
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    token = os.environ["DISCORD_TOKEN"]

    args = sys.argv[1:]
    texto = "Online."
    depois = None
    limite = 600.0
    resto = []
    while args:
        a = args.pop(0)
        if a == "--texto":
            texto = args.pop(0)
        elif a == "--depois":
            depois = args.pop(0)
        else:
            resto.append(a)
    if resto:
        limite = float(resto[0])

    def req(caminho):
        r = urllib.request.Request(
            f"{API}{caminho}",
            headers={"Authorization": f"Bot {token}",
                     "User-Agent": "DiscordBot (atlas-prova, 1.0)"},
        )
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, None

    comeco = time.monotonic()
    while time.monotonic() - comeco < limite:
        caminho = f"/channels/{CANAL}/messages?limit=20"
        if depois:
            caminho += f"&after={depois}"
        st, msgs = req(caminho)
        if st != 200:
            print(f"  [http {st}] nao deu para ler o canal")
        else:
            achados = [
                m for m in msgs
                if m["author"]["id"] == str(BOT_ID) and texto.lower() in texto_de(m).lower()
            ]
            if achados:
                m = sorted(achados, key=lambda x: x["id"])[-1]
                print(f"AVISO RECEBIDO em {time.monotonic() - comeco:.0f}s | id {m['id']}")
                print(f"  flags={m.get('flags', 0)} "
                      f"components_v2={bool(m.get('flags', 0) & 32768)}")
                print(f"  texto: {texto_de(m)[:120]!r}")
                return 0
        time.sleep(10)
        print(f"  ...{time.monotonic() - comeco:.0f}s")
    print("NAO CHEGOU AVISO")
    return 1


if __name__ == "__main__":
    sys.exit(main())
