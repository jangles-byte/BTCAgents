#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  BTCAgents — launch the dashboard (web UI + API).
#  Then, in the browser:  ▶ Run System  →  Enable Buying (when you're ready).
#  Double-click this file, or run:  ./START.command
#  Ctrl-C here stops the dashboard AND the agent loop.
# ─────────────────────────────────────────────────────────────────────────────
cd "$(dirname "$0")" || exit 1
PORT="${CONFIG_PORT:-5057}"

echo "════════════════════════════════════════════"
echo "  BTCAgents  ·  BTC up/down 15m  ·  Kalshi"
echo "════════════════════════════════════════════"

# venv + deps (first run only)
if [ ! -d venv ]; then
  echo "› First run: creating venv and installing dependencies (a few minutes)…"
  python3 -m venv venv || { echo "Could not create venv. Is python3 installed?"; exit 1; }
  ./venv/bin/pip install -q --upgrade pip
  ./venv/bin/pip install -q . && ./venv/bin/pip install -q -r requirements_btc.txt
fi
# shellcheck disable=SC1091
source venv/bin/activate

# free the port if an old instance is bound
EXIST=$(lsof -ti tcp:"$PORT" 2>/dev/null)
[ -n "$EXIST" ] && { echo "› Freeing port $PORT (old instance)…"; kill -9 $EXIST 2>/dev/null; sleep 1; }

# kill ANY orphaned agent-loop from a previous run (these run detached and keep
# executing OLD code — the #1 cause of changes 'not taking effect')
if pgrep -f "btc_kalshi.runner" >/dev/null 2>&1; then
  echo "› Killing orphaned agent loop(s) from a previous run…"
  pkill -9 -f "btc_kalshi.runner" 2>/dev/null; sleep 1
fi

# stop the agent loop too when this window is closed
cleanup(){ echo; echo "› Stopping…"; python -c "from btc_kalshi import procman; procman.stop_runner()" 2>/dev/null; exit 0; }
trap cleanup INT TERM

echo "› Dashboard  →  http://127.0.0.1:$PORT"
echo "  In the browser:  ▶ Run System , then  Enable Buying  when ready."
echo "  Ctrl-C here stops the dashboard and the agent loop."
echo "────────────────────────────────────────────"

# open the browser once the server answers
( for i in {1..20}; do curl -s "http://127.0.0.1:$PORT/api/price" >/dev/null 2>&1 && break; sleep 0.5; done; \
  open "http://127.0.0.1:$PORT" 2>/dev/null ) &

python -m config_app.app
cleanup
