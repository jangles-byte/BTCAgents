#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  BTCAgents — push to GitHub  (github.com/jangles-byte/BTCAgents)
#  SECRET-SAFE: never commits bot_config.json, *.pem, .env, or a real key value.
#  Run:  ./PUSH_TO_GITHUB.command  ["optional commit message"]
# ─────────────────────────────────────────────────────────────────────────────
cd "$(dirname "$0")" || exit 1
REPO="https://github.com/jangles-byte/BTCAgents.git"

# 1) ensure secrets are always ignored
touch .gitignore
for pat in "bot_config.json" "*.pem" "venv/" "__pycache__/" "*.pid" ".env" "btc_kalshi/data/"; do
  grep -qxF "$pat" .gitignore || echo "$pat" >> .gitignore
done

# 2) clean repo if there are no commits yet (also repairs the partial clone that
#    was left behind, which pointed at the wrong remote)
if ! git rev-parse --git-dir >/dev/null 2>&1 || ! git rev-parse HEAD >/dev/null 2>&1; then
  echo "› Initializing a fresh git repository…"; rm -rf .git; git init -b main >/dev/null
fi

# 3) point origin at YOUR repo (fixes any leftover remote)
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REPO"
else
  git remote add origin "$REPO"
fi

# 4) make sure no secret is tracked, then stage (respecting .gitignore)
git rm --cached -r --ignore-unmatch bot_config.json '*.pem' >/dev/null 2>&1
git add -A
STAGED=$(git diff --cached --name-only)

# 5) HARD GATE — never commit a secret FILE (this is the real protection)
if echo "$STAGED" | grep -qiE '(^|/)bot_config\.json$|(^|/)\.env$|\.pem$|\.pid$'; then
  echo "✋ ABORT: a secret file is staged — nothing was pushed:"
  echo "$STAGED" | grep -iE 'bot_config\.json$|\.env$|\.pem$|\.pid$' | sed 's/^/     /'
  exit 1
fi

# 6) scan for real key VALUES, skipping our own source + example files (which
#    legitimately contain the words "PRIVATE KEY" / "KALSHI-ACCESS-KEY" as code)
SCANFILES=$(echo "$STAGED" | grep -vE '(^|/)(config\.py|kalshi\.py)$|\.(example|sample)\.')
if [ -n "$SCANFILES" ] && git diff --cached -- $SCANFILES 2>/dev/null \
     | grep -qE 'sk-ant-api[0-9A-Za-z_-]{20,}|^\+[A-Za-z0-9+/]{60,}={0,2}$'; then
  echo "✋ ABORT: a real key value appears in a staged file — nothing was pushed."
  exit 1
fi
echo "› Secret check passed — no key files or key values staged."

# 7) commit + push
MSG="${1:-update $(date '+%Y-%m-%d %H:%M')}"
git commit -m "$MSG" >/dev/null 2>&1 || echo "› Nothing new to commit."
git branch -M main
echo "› Pushing to $REPO …"
if git push -u origin main; then
  echo "✓ Pushed to github.com/jangles-byte/BTCAgents"
else
  echo "✗ Push failed. If the remote already has commits, run:"
  echo "    git pull --rebase origin main      # then run this again"
  echo "  (the first push may prompt for your GitHub login / token.)"
fi
