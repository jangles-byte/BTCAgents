#!/bin/bash
# BTCAgents — ask Kalshi directly what actually happened (balance, positions,
# orders + status, fills, settlements). Double-click, or run ./DIAGNOSE.command
cd "$(dirname "$0")" || exit 1
[ -d venv ] && source venv/bin/activate
python -m btc_kalshi.diag
echo
read -p "Press Return to close."
