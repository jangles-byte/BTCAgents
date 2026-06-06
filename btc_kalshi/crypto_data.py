"""btc_kalshi.crypto_data — BTC spot / OHLCV / technical features for the analyst agents.

Pure-stdlib + requests (no pandas needed) so it runs anywhere. Pulls from public
exchange endpoints with automatic fallback (Coinbase -> Kraken -> Binance), since
availability varies by region. Everything here is READ-ONLY market data; no keys
required for the core feeds.

Public API:
    get_spot()                      -> float | None
    get_klines(interval, limit)     -> list[dict]   (oldest..newest)
    compute_features(klines)        -> dict
    build_market_report(strike=..)  -> str          (markdown, fed to Market Analyst)
"""
from __future__ import annotations

import statistics
import time
from datetime import datetime, timezone

import requests

_session = requests.Session()
_session.headers.update({"User-Agent": "BTCAgents/1.0"})
TIMEOUT = 8


# ───────────────────────── spot price (with fallback) ─────────────────────────
def get_spot() -> float | None:
    """Latest BTC/USD spot. Tries Coinbase, then Kraken, then Binance."""
    # Coinbase
    try:
        r = _session.get("https://api.exchange.coinbase.com/products/BTC-USD/ticker", timeout=TIMEOUT)
        if r.ok:
            return float(r.json()["price"])
    except Exception:
        pass
    # Kraken
    try:
        r = _session.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD", timeout=TIMEOUT)
        if r.ok:
            res = r.json()["result"]
            k = next(iter(res.values()))
            return float(k["c"][0])
    except Exception:
        pass
    # Binance
    try:
        r = _session.get("https://api.binance.com/api/v3/ticker/price",
                         params={"symbol": "BTCUSDT"}, timeout=TIMEOUT)
        if r.ok:
            return float(r.json()["price"])
    except Exception:
        pass
    return None


# ───────────────────────── candles (with fallback) ───────────────────────────
def _klines_binance(interval: str, limit: int) -> list[dict]:
    r = _session.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": "BTCUSDT", "interval": interval, "limit": limit},
                     timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for c in r.json():
        out.append({"t": int(c[0] / 1000), "o": float(c[1]), "h": float(c[2]),
                    "l": float(c[3]), "c": float(c[4]), "v": float(c[5])})
    return out


_CB_GRAN = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


def _klines_coinbase(interval: str, limit: int) -> list[dict]:
    gran = _CB_GRAN.get(interval, 60)
    r = _session.get("https://api.exchange.coinbase.com/products/BTC-USD/candles",
                     params={"granularity": gran}, timeout=TIMEOUT)
    r.raise_for_status()
    # Coinbase returns newest..oldest: [time, low, high, open, close, volume]
    rows = sorted(r.json(), key=lambda x: x[0])[-limit:]
    return [{"t": int(c[0]), "o": float(c[3]), "h": float(c[2]),
             "l": float(c[1]), "c": float(c[4]), "v": float(c[5])} for c in rows]


def get_klines(interval: str = "1m", limit: int = 60) -> list[dict]:
    """OHLCV candles, oldest..newest. interval in {1m,5m,15m,1h}."""
    for fn in (_klines_coinbase, _klines_binance):
        try:
            k = fn(interval, limit)
            if k:
                return k
        except Exception:
            continue
    return []


# ───────────────────────── technical features ────────────────────────────────
def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[-period:]) / period
    avg_l = sum(losses[-period:]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return round(100 - (100 / (1 + rs)), 1)


def compute_features(klines: list[dict]) -> dict:
    """Short-horizon technical features relevant to a 15-minute up/down bet."""
    if not klines:
        return {}
    closes = [c["c"] for c in klines]
    vols = [c["v"] for c in klines]
    last = closes[-1]

    def ret(n):
        return round((last / closes[-n - 1] - 1) * 100, 3) if len(closes) > n else None

    # realized vol from 1m log-ish returns (pct)
    rets = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
    vol_1m = round(statistics.pstdev(rets[-30:]) * 100, 4) if len(rets) >= 5 else None

    ema9, ema21 = _ema(closes[-30:], 9), _ema(closes[-30:], 21)
    return {
        "last": last,
        "ret_1m": ret(1),
        "ret_5m": ret(5),
        "ret_15m": ret(15),
        "rsi_14": _rsi(closes, 14),
        "ema9": round(ema9, 2) if ema9 else None,
        "ema21": round(ema21, 2) if ema21 else None,
        "ema_trend": ("up" if ema9 and ema21 and ema9 > ema21
                      else "down" if ema9 and ema21 else None),
        "vol_1m_pct": vol_1m,
        "vol_last": round(vols[-1], 2) if vols else None,
        "vol_avg": round(sum(vols[-20:]) / min(20, len(vols)), 2) if vols else None,
        "n_candles": len(klines),
    }


# ───────────────────────── analyst-facing report ─────────────────────────────
def build_market_report(strike: float | None = None, mins_remaining: float | None = None) -> str:
    """Markdown technical snapshot the Market Analyst consumes. If a Kalshi strike
    and time-left are supplied, distance-to-strike is included (the thing that
    actually decides a 15-minute up/down contract)."""
    spot = get_spot()
    k1 = get_klines("1m", 60)
    k15 = get_klines("15m", 16)
    f = compute_features(k1)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [f"# BTC Technical Snapshot ({now})", ""]
    lines.append(f"- Spot (BTC/USD): **{spot if spot else 'n/a'}**")
    if f:
        lines += [
            f"- Returns: 1m {f.get('ret_1m')}% | 5m {f.get('ret_5m')}% | 15m {f.get('ret_15m')}%",
            f"- RSI(14, 1m): {f.get('rsi_14')}",
            f"- EMA9 {f.get('ema9')} vs EMA21 {f.get('ema21')} -> trend **{f.get('ema_trend')}**",
            f"- Realized vol (1m, pct stdev): {f.get('vol_1m_pct')}",
            f"- Volume last {f.get('vol_last')} vs 20-avg {f.get('vol_avg')}",
        ]
    if strike is not None and spot is not None:
        dist = spot - strike
        lines.append(f"- Distance to strike {strike}: **{dist:+.2f}** "
                     f"({'above (YES/up favored)' if dist > 0 else 'below (NO/down favored)'})")
        if f and f.get("vol_1m_pct") and mins_remaining:
            # crude move budget: 1m stdev (in $) * sqrt(minutes left)
            sigma_dollars = spot * f["vol_1m_pct"] / 100.0
            budget = sigma_dollars * (max(mins_remaining, 0) ** 0.5)
            lines.append(f"- ~1-sigma move budget over {mins_remaining:.1f} min: "
                         f"±{budget:,.0f} (strike is {abs(dist)/budget:.2f} sigma away)"
                         if budget else "")
    if k15:
        closes = [c["c"] for c in k15]
        lines.append(f"- Last 15m candles close range: {min(closes):,.0f}–{max(closes):,.0f}")
    return "\n".join([l for l in lines if l != ""])


if __name__ == "__main__":
    print(build_market_report())
