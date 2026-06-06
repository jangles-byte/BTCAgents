"""CandleKiller — Kalshi API layer.

Market data (markets, prices) always reads from PRODUCTION with account-1
credentials, so prices are real regardless of which account trades. Orders /
balance use the ACTIVE account (account 2 routes to the demo endpoint).
"""
from __future__ import annotations
import base64, re, time, uuid, json as _json
from datetime import datetime, timezone
import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from . import config

_session = requests.Session()


def _sign(key_id: str, private_key, method: str, path: str) -> dict:
    ts = str(int(time.time() * 1000))
    msg = f"{ts}{method.upper()}{path}".encode()
    sig = private_key.sign(
        msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        "Content-Type": "application/json",
    }


def parse_strike(ticker: str):
    """Dollar strike from a KXBTC15M ticker (…-T67500 / trailing integer)."""
    m = re.search(r'-[TtBb](\d+(?:\.\d+)?)$', ticker)
    if m:
        return float(m.group(1))
    m = re.search(r'(\d{4,6})$', ticker)
    if m:
        v = float(m.group(1))
        if 10_000 < v < 500_000:
            return v
    return None


def _mkt_price(m: dict, *keys):
    """Bid/ask from a Kalshi market dict — handles cents (0-100) or dollars (0-1)."""
    for k in keys:
        v = m.get(k)
        if v is not None:
            try:
                f = float(v)
                return f / 100.0 if f > 1.0 else f
            except (TypeError, ValueError):
                pass
    return None


def get_front_market(min_minutes: float = 0.0) -> dict | None:
    """The active KXBTC15M market: nearest future close_time with at least
    `min_minutes` left. Returns a dict with ticker, strike, mins_remaining,
    yes/no ask+bid, close_ts — or None."""
    kid, pk, prod_id, prod_key, base, acct = config.get_credentials()
    if not prod_id or not prod_key:
        return None
    path = "/trade-api/v2/markets"
    try:
        r = _session.get(config.KALSHI_PROD_BASE + "/markets",
                         headers=_sign(prod_id, prod_key, "GET", path),
                         params={"series_ticker": "KXBTC15M", "status": "open", "limit": 8},
                         timeout=6)
        markets = r.json().get("markets", [])
    except Exception:
        return None
    now = datetime.now(timezone.utc)
    best, best_diff = None, float("inf")
    for m in markets:
        try:
            close = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
        except Exception:
            continue
        diff = (close - now).total_seconds()
        if (min_minutes * 60.0) < diff < best_diff:
            best_diff, best = diff, m
    if not best:
        return None
    yb = _mkt_price(best, "yes_bid_dollars", "yes_bid")
    ya = _mkt_price(best, "yes_ask_dollars", "yes_ask")
    ticker = best.get("ticker", "")
    strike = parse_strike(ticker)
    if strike is None:
        # Some markets carry the strike as a field rather than in the ticker.
        for f in ("cap_strike", "floor_strike", "strike"):
            if best.get(f):
                try: strike = float(best[f]); break
                except Exception: pass
    return {
        "ticker": ticker,
        "strike": strike,
        "close_ts": now.timestamp() + best_diff,
        "mins_remaining": round(best_diff / 60.0, 2),
        "yes_ask": ya, "no_ask": (round(1.0 - yb, 4) if yb is not None else None),
        "yes_bid": yb, "no_bid": (round(1.0 - ya, 4) if ya is not None else None),
    }


def get_balance() -> float | None:
    kid, pk, *_ = config.get_credentials()
    _, _, _, _, base, _ = config.get_credentials()
    if not kid or not pk:
        return None
    path = "/trade-api/v2/portfolio/balance"
    try:
        r = _session.get(base + "/portfolio/balance",
                         headers=_sign(kid, pk, "GET", path), timeout=6)
        return r.json().get("balance", 0) / 100.0
    except Exception:
        return None


def _post_order(kid, pk, base, body: dict) -> dict:
    """POST an order and NORMALIZE errors. Kalshi rejects with {code, message,
    details} and NO 'error' key — so a 400 used to look like success. Here we
    map any non-2xx (or transport failure) to {'error': ...} so callers can tell."""
    path = "/trade-api/v2/portfolio/orders"
    try:
        r = _session.post(base + "/portfolio/orders",
                          headers=_sign(kid, pk, "POST", path),
                          data=_json.dumps(body), timeout=8)
        try:
            j = r.json()
        except Exception:
            j = {}
        if r.status_code >= 400:
            msg = j.get("message") or j.get("error") or j.get("code") or (r.text or "")[:200]
            return {"error": f"HTTP {r.status_code}: {msg}", "raw": j}
        return j                                  # 201 → {"order": {...}}
    except Exception as e:
        return {"error": str(e)}


def place_order(ticker: str, side: str, count: int, price_dollars: float) -> dict:
    """Place a buy LIMIT order at price_dollars on the ACTIVE account. A
    marketable price (≈ask) fills like a market order; a low price rests."""
    kid, pk, _, _, base, acct = config.get_credentials()
    if not kid or not pk:
        return {"error": "no credentials for active account"}
    body = {
        "ticker": ticker, "client_order_id": str(uuid.uuid4()),
        "action": "buy", "side": side, "type": "limit",
        "count": int(count), f"{side}_price_dollars": f"{price_dollars:.4f}",
    }
    return _post_order(kid, pk, base, body)


def place_sell_order(ticker: str, side: str, count: int, price_dollars: float) -> dict:
    """RESTING (good-till-canceled) SELL limit to CLOSE a held position at
    price_dollars — a take-profit. It rests until the market trades to the price,
    then fills automatically; no tape-watching. NOTE: `reduce_only` is NOT used —
    Kalshi only allows reduce_only on immediate-or-cancel orders, and a take-profit
    must rest. Overselling is prevented by the caller verifying the real held
    quantity (get_positions) and selling exactly that. Works on whichever account
    is active (real or demo) since base+creds come from get_credentials()."""
    kid, pk, _, _, base, acct = config.get_credentials()
    if not kid or not pk:
        return {"error": "no credentials for active account"}
    body = {
        "ticker": ticker, "client_order_id": str(uuid.uuid4()),
        "action": "sell", "side": side, "type": "limit",
        "count": int(count), f"{side}_price_dollars": f"{price_dollars:.4f}",
        "time_in_force": "good_till_canceled",   # rest in the book until the price is hit
    }
    return _post_order(kid, pk, base, body)


def get_positions() -> list:
    """Live market positions on the ACTIVE account. Each item has `ticker` and a
    signed `position` (>0 long YES, <0 long NO). Used to confirm a fill before
    resting a take-profit sell."""
    kid, pk, _, _, base, _ = config.get_credentials()
    if not kid or not pk:
        return []
    path = "/trade-api/v2/portfolio/positions"
    try:
        r = _session.get(base + "/portfolio/positions",
                         headers=_sign(kid, pk, "GET", path),
                         params={"limit": 200}, timeout=8)
        return r.json().get("market_positions", []) or []
    except Exception:
        return []


def get_settlements(limit: int = 50) -> list:
    """Recent KXBTC15M settlements on the active account (for PnL reconcile)."""
    kid, pk, _, _, base, _ = config.get_credentials()
    if not kid or not pk:
        return []
    path = "/trade-api/v2/portfolio/settlements"
    try:
        r = _session.get(base + "/portfolio/settlements",
                         headers=_sign(kid, pk, "GET", path),
                         params={"limit": limit}, timeout=8)
        return [s for s in r.json().get("settlements", [])
                if str(s.get("ticker", "")).startswith("KXBTC15M")]
    except Exception:
        return []
