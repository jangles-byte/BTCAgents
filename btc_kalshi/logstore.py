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
              "mins_remaining", "ticker", "reason", "placed", "order_status",
              "after_position", "book_ask", "book_src", "error", "dry_run", "balance_usd")}
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


# ── live cycle heartbeat (so the dashboard shows analyzing vs idle, truthfully) ─
_STATUS = cfg.PROJECT_ROOT / "btc_kalshi" / "data" / "status.json"


def set_status(phase: str, **extra) -> None:
    d = {"phase": phase, "ts": time.time(), **extra}
    _STATUS.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATUS.with_suffix(".statustmp")
    tmp.write_text(json.dumps(d))
    tmp.replace(_STATUS)


def read_status() -> dict:
    try:
        return json.loads(_STATUS.read_text())
    except Exception:
        return {"phase": "idle"}


# ── trades THIS bot actually placed (so history excludes old account activity) ──
_TRADES = cfg.PROJECT_ROOT / "btc_kalshi" / "data" / "our_trades.json"


def record_trade(rec: dict) -> None:
    rows = read_trades(2000)
    rec = dict(rec)
    rec.setdefault("ts", time.time())
    rows.append(rec)
    _TRADES.parent.mkdir(parents=True, exist_ok=True)
    tmp = _TRADES.with_suffix(".ttmp")
    tmp.write_text(json.dumps(rows[-2000:], indent=2))
    tmp.replace(_TRADES)


def read_trades(n: int = 200) -> list:
    try:
        return json.loads(_TRADES.read_text())[-n:]
    except Exception:
        return []
