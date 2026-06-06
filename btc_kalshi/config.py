"""CandleKiller — configuration, credentials, and account routing.

Self-contained. Reads everything from bot_config.json (copy yours in).
Inline PEMs in the config are preferred over file paths, so it works the
moment you drop your bot_config.json next to these files — no path fixing.
"""
from __future__ import annotations
import json, os, tempfile, threading, time
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_private_key

BOT_DIR = Path(__file__).parent
PROJECT_ROOT = BOT_DIR.parent
CONFIG_FILE   = PROJECT_ROOT / "bot_config.json"
RULES_FILE    = BOT_DIR / "data" / "ai_rules.json"
BRIEFING_FILE = BOT_DIR / "data" / "candle_briefing.md"
FORECAST_FILE = BOT_DIR / "data" / "candle_forecast.json"
MARKET_FILE   = BOT_DIR / "data" / "market_state.json"
POSITION_FILE = BOT_DIR / "data" / "current_position.json"
CALIB_FILE    = BOT_DIR / "data" / "calibration.json"
TRADES_FILE   = BOT_DIR / "data" / "trades.csv"

# Kalshi endpoints — production for market data, demo when account 2 trades.
KALSHI_PROD_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_DEMO_BASE = "https://external-api.demo.kalshi.co/trade-api/v2"

_cfg_lock = threading.Lock()


# ── config / rules I/O (atomic — never tears the file under concurrent writes) ──
def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}

def save_config(cfg: dict):
    _atomic_write(CONFIG_FILE, cfg)

def update_config(**keys):
    with _cfg_lock:
        cfg = load_config()
        cfg.update(keys)
        _atomic_write(CONFIG_FILE, cfg)
        return cfg

def load_rules() -> dict:
    try:
        return json.loads(RULES_FILE.read_text())
    except Exception:
        return {}

def save_rules(rules: dict):
    _atomic_write(RULES_FILE, rules)

def _atomic_write(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.stem + "_", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2)
        os.replace(tmp, str(path))
    except Exception:
        try: os.unlink(tmp)
        except Exception: pass
        raise


# ── credentials ────────────────────────────────────────────────────────────
def _load_key(pem_inline: str | None, pem_path: str | None):
    """Load an RSA private key from an inline PEM (preferred) or a file path."""
    pem = (pem_inline or "").strip()
    if pem and not pem.startswith("•"):
        if "BEGIN" not in pem:
            pem = "-----BEGIN RSA PRIVATE KEY-----\n" + pem + "\n-----END RSA PRIVATE KEY-----"
        try:
            return load_pem_private_key(pem.encode(), password=None)
        except Exception:
            pass
    if pem_path and os.path.exists(pem_path):
        try:
            return load_pem_private_key(open(pem_path, "rb").read(), password=None)
        except Exception:
            pass
    return None


def get_credentials():
    """Return (active_key_id, active_private_key, prod_key_id, prod_private_key,
    active_base_url, active_account).

    Account 1 is treated as production (market data always uses it). The active
    account (1 or 2) is used for orders/balance; account 2 routes to demo.
    """
    cfg = load_config()
    # account 1 (production / market data)
    k1_id  = cfg.get("kalshi_api_key_id") or os.getenv("KALSHI_API_KEY_ID")
    k1_key = _load_key(cfg.get("kalshi_private_key_pem"),
                       cfg.get("kalshi_private_key_path") or os.getenv("KALSHI_PRIVATE_KEY_PATH"))
    # account 2 (demo / testing)
    k2_id  = cfg.get("kalshi_api_key_id_2")
    k2_key = _load_key(cfg.get("kalshi_private_key_pem_2"),
                       cfg.get("kalshi_private_key_path_2"))
    base2  = (cfg.get("kalshi_base_url_2") or KALSHI_DEMO_BASE).rstrip("/")

    active = int(cfg.get("active_account", 1) or 1)
    if active == 2 and k2_id and k2_key:
        return k2_id, k2_key, k1_id, k1_key, base2, 2
    return k1_id, k1_key, k1_id, k1_key, KALSHI_PROD_BASE, 1
