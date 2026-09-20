#!/usr/bin/env bash
# Coloca o Atlas no ar no GitHub Actions.
#
# Uso:
#   GITHUB_TOKEN=ghp_xxx bash scripts/publicar_no_actions.sh [nome-do-repo]
#
# O que faz:
#   1. cria o repo no seu GitHub (publico, por causa dos minutos - veja abaixo)
#   2. grava DISCORD_TOKEN como secret, sem nunca imprimir o valor
#   3. da push na branch main
#   4. dispara o workflow e mostra a URL para acompanhar
#
# Por que publico: repo privado tem 2.000 minutos/mes de Actions, e 24/7 precisa
# de ~43.200. Publico nao tem limite de minutos. O .env fica fora do git, entao
# o token do bot nao vai junto - so o codigo fica visivel.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="${1:-atlas-bot}"
API="https://api.github.com"

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "Falta o GITHUB_TOKEN. Gere em:"
  echo "  https://github.com/settings/tokens/new  (escopo: repo)"
  echo "e rode:  GITHUB_TOKEN=ghp_xxx bash scripts/publicar_no_actions.sh"
  exit 1
fi

# O token do bot vem do .env, nao do ambiente - e nunca e impresso.
if [ -z "${DISCORD_TOKEN:-}" ] && [ -f .env ]; then
  DISCORD_TOKEN="$(grep '^DISCORD_TOKEN=' .env | head -1 | cut -d= -f2-)"
  export DISCORD_TOKEN
fi
if [ -z "${DISCORD_TOKEN:-}" ]; then
  echo "DISCORD_TOKEN vazio no .env - nada a gravar como secret."
  exit 1
fi

# cifra com o python do venv quando existe (tem pynacl); senao o do sistema
PYBIN=".venv/bin/python"; [ -x "$PYBIN" ] || PYBIN="python3"

auth() { curl -sS -H "Authorization: Bearer $GITHUB_TOKEN" \
              -H "Accept: application/vnd.github+json" \
              -H "User-Agent: atlas-setup" "$@"; }

echo "== 1/5 quem sou eu no GitHub =="
EU=$(auth "$API/user" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("login",""))')
if [ -z "$EU" ]; then
  echo "Token invalido ou sem permissao. Confira em https://github.com/settings/tokens"
  exit 1
fi
echo "   conta: $EU"

echo "== 2/5 criando o repo $EU/$REPO =="
CRIADO=$(auth -X POST "$API/user/repos" -d "{\"name\":\"$REPO\",\"private\":false,\"auto_init\":false}")
if echo "$CRIADO" | grep -q '"full_name"'; then
  echo "   criado"
elif echo "$CRIADO" | grep -qi 'already exists'; then
  echo "   ja existe, vou usar o que esta la"
else
  echo "   falhou: $CRIADO" | head -3
  exit 1
fi

echo "== 3/5 gravando o secret DISCORD_TOKEN =="
# O GitHub exige cifrar o valor com a chave publica do repo (libsodium sealed box).
# Nada do token vai para o log.
"$PYBIN" - "$REPO" "$EU" <<'PY'
import base64, json, os, sys, urllib.request
repo, dono = sys.argv[1], sys.argv[2]
tok = os.environ["GITHUB_TOKEN"]
dis = os.environ["DISCORD_TOKEN"]
H = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
     "User-Agent": "atlas-setup"}

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=30) as r:
        return json.load(r)

chave = get(f"https://api.github.com/repos/{dono}/{repo}/actions/secrets/public-key")
try:
    from nacl import encoding, public
    sealed = public.SealedBox(public.PublicKey(chave["key"].encode(), encoding.Base64Encoder)).encrypt(dis.encode())
    cifrado = base64.b64encode(sealed).decode()
except ImportError:
    sys.exit("NECESSITA_PYNACL")

body = json.dumps({"encrypted_value": cifrado, "key_id": chave["key_id"]}).encode()
req = urllib.request.Request(
    f"https://api.github.com/repos/{dono}/{repo}/actions/secrets/DISCORD_TOKEN",
    data=body, headers={**H, "Content-Type": "application/json"}, method="PUT")
with urllib.request.urlopen(req, timeout=30) as r:
    print(f"   gravado (HTTP {r.status})")
PY
if [ $? -ne 0 ]; then
  echo "   Faltou a lib de criptografia. Rode: pip install pynacl"
  exit 1
fi

echo "== 4/5 push =="
git remote remove origin 2>/dev/null || true
git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/$EU/$REPO.git"
git branch -M main
git push -u origin main --force
git remote set-url origin "https://github.com/$EU/$REPO.git"   # nao deixa o token no .git/config

echo "== 5/5 disparando o workflow =="
auth -X POST "$API/repos/$EU/$REPO/actions/workflows/bot.yml/dispatches" \
     -d '{"ref":"main"}' >/dev/null && echo "   disparado"

echo
echo "Pronto. Acompanhe em:"
echo "  https://github.com/$EU/$REPO/actions"
echo
echo "O bot sobe em ~1 minuto e roda em turnos de 6h, religando sozinho por cron."
echo "IMPORTANTE: desligue qualquer bot rodando em outro lugar com o mesmo token,"
echo "senao os dois brigam pela sessao do Discord."
