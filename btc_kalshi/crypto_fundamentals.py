"""btc_kalshi.crypto_fundamentals — the BTC-relevant "fundamentals":
perp funding, open interest, long/short positioning.

Primary source is COINALYZE (works from the US, uses your coinalyze_api_key);
Binance Futures is a fallback but is usually geo-blocked in the US. The funding
report the agents read uses these same functions.
"""
from __future__ import annotations

import requests

from . import config as cfg, crypto_data

_session = requests.Session()
_session.headers.update({"User-Agent": "BTCAgents/1.0"})
TIMEOUT = 8
_FAPI = "https://fapi.binance.com"
_CA = "https://api.coinalyze.net/v1"
_CA_SYMBOL = "BTCUSD_PERP.A"   # Binance BTC perp on Coinalyze (verified in agent log)


def _ca_key():
    return cfg.load_config().get("coinalyze_api_key") or None


def coinalyze_raw(path: str, params: dict):
    """Raw Coinalyze GET (used by feeds + the diagnostic). Returns (json, error)."""
    key = _ca_key()
    if not key:
        return None, "no coinalyze_api_key set"
    try:
        r = _session.get(_CA + path, headers={"api_key": key}, params=params, timeout=TIMEOUT)
        if r.status_code >= 400:
            return None, f"HTTP {r.status_code}: {r.text[:160]}"
        return r.json(), None
    except Exception as e:
        return None, str(e)


def _ca_value(j):
    """Coinalyze list endpoints return [{symbol, value, update}, ...]."""
    if isinstance(j, list) and j and isinstance(j[0], dict):
        for k in ("value", "funding_rate", "rate", "oi", "open_interest", "r"):
            v = j[0].get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
    return None


def get_funding() -> dict:
    return crypto_data.cached("fund:funding", 30.0, _funding_uncached)


def _funding_uncached() -> dict:
    # Coinalyze first (value is a decimal fraction, e.g. -0.0008 = -0.08%)
    j, err = coinalyze_raw("/funding-rate", {"symbols": _CA_SYMBOL})
    v = _ca_value(j)
    if v is not None:
        return {"funding_rate": round(v * 100, 4), "source": "coinalyze"}
    # Binance fallback (often US-blocked)
    try:
        r = _session.get(f"{_FAPI}/fapi/v1/premiumIndex", params={"symbol": "BTCUSDT"}, timeout=TIMEOUT)
        if r.ok:
            d = r.json()
            return {"funding_rate": round(float(d.get("lastFundingRate", 0)) * 100, 4),
                    "mark_price": float(d.get("markPrice", 0)), "source": "binance"}
    except Exception:
        pass
    return {"error": err or "unavailable"}


def get_open_interest() -> dict:
    return crypto_data.cached("fund:oi", 30.0, _oi_uncached)


def _oi_uncached() -> dict:
    j, err = coinalyze_raw("/open-interest", {"symbols": _CA_SYMBOL, "convert_to_usd": "false"})
    v = _ca_value(j)
    if v is not None:
        return {"open_interest_btc": round(v, 2), "source": "coinalyze"}
    try:
        r = _session.get(f"{_FAPI}/fapi/v1/openInterest", params={"symbol": "BTCUSDT"}, timeout=TIMEOUT)
        if r.ok:
            return {"open_interest_btc": float(r.json().get("openInterest", 0)), "source": "binance"}
    except Exception:
        pass
    return {"error": err or "unavailable"}


def get_long_short_ratio() -> dict:
    return crypto_data.cached("fund:ls", 30.0, _ls_uncached)


def _ls_uncached() -> dict:
    # Coinalyze long/short ratio history (take the latest point)
    j, err = coinalyze_raw("/long-short-ratio-history",
                           {"symbols": _CA_SYMBOL, "interval": "5min"})
    try:
        if isinstance(j, list) and j and j[0].get("history"):
            last = j[0]["history"][-1]
            r = last.get("r") or last.get("ratio") or last.get("value")
            if r is not None:
                return {"long_short_ratio": round(float(r), 3), "source": "coinalyze"}
    except Exception:
        pass
    try:
        r = _session.get(f"{_FAPI}/futures/data/globalLongShortAccountRatio",
                         params={"symbol": "BTCUSDT", "period": "5m", "limit": 1}, timeout=TIMEOUT)
        if r.ok and r.json():
            return {"long_short_ratio": round(float(r.json()[-1]["longShortRatio"]), 3), "source": "binance"}
    except Exception:
        pass
    return {}


def build_fundamentals_report(coinalyze_key: str | None = None) -> str:
    """Markdown derivatives/positioning snapshot — the BTC stand-in for fundamentals."""
    fund = get_funding()
    oi = get_open_interest()
    lsr = get_long_short_ratio()

    lines = ["# BTC Positioning & Flows (derivatives 'fundamentals')", ""]
    fr = fund.get("funding_rate")
    if fr is not None:
        bias = ("longs paying shorts (bullish-crowded)" if fr > 0
                else "shorts paying longs (bearish-crowded)")
        lines.append(f"- Perp funding rate: **{fr:+.4f}%** — {bias}  _(src: {fund.get('source')})_")
    else:
        lines.append(f"- Perp funding: unavailable ({fund.get('error')})")
    if oi.get("open_interest_btc") is not None:
        lines.append(f"- Open interest: {oi['open_interest_btc']}  _(src: {oi.get('source')})_")
    if lsr.get("long_short_ratio") is not None:
        r = lsr["long_short_ratio"]
        lines.append(f"- Long/short ratio: **{r}** ({'crowd net long' if r > 1 else 'crowd net short'})")
    if len(lines) <= 2:
        lines.append("- (No derivatives data available right now.)")
    lines += [
        "",
        "_Interpretation: extreme funding + rising OI often precedes mean-reverting "
        "squeezes; neutral funding with flat OI favors range/continuation. Weigh against "
        "the short-term technical trend and the contract's implied probability._",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(build_fundamentals_report())
