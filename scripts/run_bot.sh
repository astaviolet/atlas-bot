#!/usr/bin/env bash
# Supervisor do bot.
#
# O runner do GitHub Actions mata qualquer job em 6 horas, sem aviso e sem
# graca. Este script existe para sobreviver a isso: roda o bot em laco,
# reinicia quando ele cai, e cada partida nasce com um prazo que expira um
# pouco antes do teto - assim o script encerra sozinho e o proximo disparo do
# cron assume sem dois bots brigando pela mesma sessao do gateway.
#
# Uso:  scripts/run_bot.sh
# Env:  MAX_RUN_SECONDS  tempo maximo desta execucao (padrao 20700 = 5h45)
#       MAX_RESTARTS     quantas reinicializacoes aceitar (padrao 200)
set -uo pipefail

cd "$(dirname "$0")/.."

MAX_RUN_SECONDS="${MAX_RUN_SECONDS:-20700}"
MAX_RESTARTS="${MAX_RESTARTS:-200}"
PYTHON="${PYTHON:-.venv/bin/python}"
LOG_DIR="${LOG_DIR:-logs}"
LOG_FILE="${LOG_DIR}/bot.log"

if [ ! -x "$PYTHON" ]; then
  # Cair em python3 sem avisar e pior que falhar: o bot entra em loop de
  # ModuleNotFoundError e o log nao diz o motivo real. Aconteceu quando o
  # .venv sumiu do sandbox.
  if ! python3 -c "import atlas" 2>/dev/null; then
    echo "[supervisor] ERRO: $PYTHON nao existe e o python3 do sistema nao tem o pacote atlas."
    echo "[supervisor] Recrie o ambiente: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e ."
    exit 1
  fi
  PYTHON="python3"
fi
mkdir -p "$LOG_DIR"

# ---------------------------------------------------------------------------
# Trava de instancia unica. Dois bots com o mesmo token brigam pela mesma
# sessao do gateway do Discord: um derruba a conexao do outro, e o usuario ve
# resposta duplicada ou nenhuma. Aconteceu de verdade - tres instancias
# rodando ao mesmo tempo. Melhor recusar a segunda do que competir.
LOCK="${LOCK_DIR:-/tmp}/atlas-bot.lock"
if [ -f "$LOCK" ]; then
  pid_antigo=$(cat "$LOCK" 2>/dev/null || echo "")
  if [ -n "$pid_antigo" ] && kill -0 "$pid_antigo" 2>/dev/null; then
    echo "[supervisor] ja existe uma instancia rodando (pid $pid_antigo). Saindo."
    echo "[supervisor] se for resto de crash, apague $LOCK e rode de novo."
    exit 0
  fi
  echo "[supervisor] trava obsoleta (pid $pid_antigo nao existe); assumindo."
fi
echo $$ > "$LOCK"
rm_lock() { [ -f "$LOCK" ] && [ "$(cat "$LOCK" 2>/dev/null)" = "$$" ] && rm -f "$LOCK"; }

INICIO=$(date +%s)
tentativa=0
falhas_rapidas=0
BOT_PID=""

encerrar() {
  echo "[supervisor] sinal recebido, derrubando o bot."
  [ -n "$BOT_PID" ] && kill -TERM "$BOT_PID" 2>/dev/null
  rm_lock
  exit 0
}
trap encerrar TERM INT
trap rm_lock EXIT

agora() { date +%s; }

echo "[supervisor] python     = $PYTHON"
echo "[supervisor] tempo teto = ${MAX_RUN_SECONDS}s"
echo "[supervisor] log        = ${LOG_FILE}"

while :; do
  decorrido=$(( $(agora) - INICIO ))
  restante=$(( MAX_RUN_SECONDS - decorrido ))
  if [ "$restante" -le 0 ]; then
    echo "[supervisor] teto de ${MAX_RUN_SECONDS}s atingido; saindo para o cron relancar."
    exit 0
  fi

  tentativa=$(( tentativa + 1 ))
  if [ "$tentativa" -gt "$MAX_RESTARTS" ]; then
    echo "[supervisor] ${MAX_RESTARTS} reinicializacoes esgotadas; desistindo."
    exit 1
  fi

  echo "[supervisor] ---- partida #${tentativa} em $(date -u +%FT%TZ), prazo ${restante}s ----"
  inicio_partida=$(agora)

  # `timeout` garante que a partida nao ultrapasse o teto MESMO com o bot
  # saudavel em foreground - sem isso o teto so seria conferido entre quedas.
  # SIGTERM primeiro, SIGKILL 30s depois se ele enrolar para sair.
  timeout --signal=TERM --kill-after=30s "$restante" \
    "$PYTHON" -u main.py > >(tee -a "$LOG_FILE") 2>&1
  codigo=$?
  BOT_PID=""

  if [ "$codigo" -eq 124 ]; then
    echo "[supervisor] prazo esgotado de forma limpa; o cron assume a partir daqui."
    exit 0
  fi

  durou=$(( $(agora) - inicio_partida ))
  if [ "$durou" -lt 30 ]; then
    falhas_rapidas=$(( falhas_rapidas + 1 ))
  else
    falhas_rapidas=0
  fi

  # Crash loop quase sempre e configuracao errada, nao queda de rede.
  if [ "$falhas_rapidas" -ge 5 ]; then
    echo "[supervisor] 5 quedas em menos de 30s seguidas. Provavel erro de configuracao."
    exit 1
  fi

  espera=$(( 5 + tentativa * 3 )); [ "$espera" -gt 60 ] && espera=60
  echo "[supervisor] bot saiu com codigo ${codigo} apos ${durou}s; aguardando ${espera}s."
  sleep "$espera"
done
