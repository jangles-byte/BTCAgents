"""btc_kalshi.logstore — append-only record of agent cycles so the dashboard can
show the latest decision, recent history, and a running tally. Tiny + atomic."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config as cfg

_FILE = cfg.PROJECT_ROOT / "btc_kalshi" / "data" / "decisions.json"


def append_decision(result: dict) -> None:
    rows = read_decisions(500)
    entry = {k: result.get(k) for k in
             ("action", "rating", "side", "count", "price_dollars", "strike",
              "mins_remaining", "ticker", "reason", "executed", "dry_run", "balance_usd")}
    entry["ts"] = time.time()
    rows.append(entry)
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows[-500:], indent=2))
    tmp.replace(_FILE)


def read_decisions(n: int = 50) -> list:
    try:
        return json.loads(_FILE.read_text())[-n:]
    except Exception:
        return []
