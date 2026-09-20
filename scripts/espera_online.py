"""Espera o aviso 'Online.' do bot hospedado aparecer no canal de controle."""
import json, os, sys, time, urllib.error, urllib.request
from dotenv import load_dotenv

API = "https://discord.com/api/v10"
BOT_ID = 1550239353802858626
CANAL = 1551015583712026768
load_dotenv()
TOKEN = os.environ["DISCORD_TOKEN"]
marco = sys.argv[1]
limite = float(sys.argv[2]) if len(sys.argv) > 2 else 600

def req(caminho):
    r = urllib.request.Request(f"{API}{caminho}", headers={
        "Authorization": f"Bot {TOKEN}",
        "User-Agent": "DiscordBot (atlas-prova, 1.0)"})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None

comeco = time.monotonic()
while time.monotonic() - comeco < limite:
    st, msgs = req(f"/channels/{CANAL}/messages?limit=20&after={marco}")
    if st == 200:
        avisos = [m for m in msgs if m["author"]["id"] == str(BOT_ID)]
        if avisos:
            m = sorted(avisos, key=lambda x: x["id"])[0]
            print(f"AVISO RECEBIDO em {time.monotonic()-comeco:.0f}s | id {m['id']}")
            print(f"  flags={m.get('flags',0)} components_v2={bool(m.get('flags',0)&32768)}")
            for c in (m.get("components") or []):
                for sub in c.get("components", []):
                    for s2 in sub.get("components", []) or [sub]:
                        if s2.get("content"):
                            print(f"  texto: {s2['content']!r}")
            sys.exit(0)
    time.sleep(10)
    print(f"  ...{time.monotonic()-comeco:.0f}s")
print("NAO CHEGOU AVISO")
sys.exit(1)
