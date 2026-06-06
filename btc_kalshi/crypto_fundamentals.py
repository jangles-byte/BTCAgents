"""btc_kalshi.crypto_fundamentals — the BTC-relevant "fundamentals".

The original TradingAgents Fundamentals Analyst reads balance sheets / income
statements. BTC has none. This module is the repurposed input source: derivatives
positioning and flows that actually move BTC on short horizons —
  - perpetual funding rate (who's paying to hold the trend)
  - open interest (leverage in the system)
  - long/short account ratio (crowd positioning)
  - optional aggregated cross-exchange data via Coinalyze (api key, optional)

Falls back gracefully when an endpoint or key is unavailable. No key needed for
the Binance-futures public feeds; Coinalyze is optional and only enriches.

Public API:
    get_funding()                 -> dict
    get_open_interest()           -> dict
    get_long_short_ratio()        -> dict
    build_fundamentals_report()   -> str (markdown, fed to the Fundamentals Analyst)
"""
from __future__ import annotations

import requests

_session = requests.Session()
_session.headers.update({"User-Agent": "BTCAgents/1.0"})
TIMEOUT = 8
_FAPI = "https://fapi.binance.com"


def get_funding() -> dict:
    try:
        r = _session.get(f"{_FAPI}/fapi/v1/premiumIndex",
                         params={"symbol": "BTCUSDT"}, timeout=TIMEOUT)
        if r.ok:
            d = r.json()
            return {
                "funding_rate": float(d.get("lastFundingRate", 0)) * 100,  # pct
                "mark_price": float(d.get("markPrice", 0)),
                "index_price": float(d.get("indexPrice", 0)),
            }
    except Exception:
        pass
    return {}


def get_open_interest() -> dict:
    out = {}
    try:
        r = _session.get(f"{_FAPI}/fapi/v1/openInterest",
                         params={"symbol": "BTCUSDT"}, timeout=TIMEOUT)
        if r.ok:
            out["open_interest_btc"] = float(r.json().get("openInterest", 0))
    except Exception:
        pass
    try:
        r = _session.get(f"{_FAPI}/futures/data/openInterestHist",
                         params={"symbol": "BTCUSDT", "period": "5m", "limit": 6}, timeout=TIMEOUT)
        if r.ok and r.json():
            hist = r.json()
            first = float(hist[0]["sumOpenInterest"])
            last = float(hist[-1]["sumOpenInterest"])
            out["oi_change_30m_pct"] = round((last / first - 1) * 100, 2) if first else None
    except Exception:
        pass
    return out


def get_long_short_ratio() -> dict:
    try:
        r = _session.get(f"{_FAPI}/futures/data/globalLongShortAccountRatio",
                         params={"symbol": "BTCUSDT", "period": "5m", "limit": 1}, timeout=TIMEOUT)
        if r.ok and r.json():
            d = r.json()[-1]
            return {"long_short_ratio": round(float(d["longShortRatio"]), 3)}
    except Exception:
        pass
    return {}


def get_coinalyze(api_key: str | None) -> dict:
    """Optional: aggregated cross-exchange funding/OI. Only runs if a key is set."""
    if not api_key:
        return {}
    try:
        r = _session.get("https://api.coinalyze.net/v1/funding-rate",
                         headers={"api_key": api_key},
                         params={"symbols": "BTCUSD_PERP.A"}, timeout=TIMEOUT)
        if r.ok:
            return {"coinalyze": r.json()}
    except Exception:
        pass
    return {}


def build_fundamentals_report(coinalyze_key: str | None = None) -> str:
    """Markdown derivatives/positioning snapshot — the BTC stand-in for fundamentals."""
    fund = get_funding()
    oi = get_open_interest()
    lsr = get_long_short_ratio()

    lines = ["# BTC Positioning & Flows (derivatives 'fundamentals')", ""]
    if fund:
        fr = fund.get("funding_rate")
        bias = ("longs paying shorts (bullish-crowded)" if fr and fr > 0
                else "shorts paying longs (bearish-crowded)" if fr is not None else "n/a")
        lines += [
            f"- Perp funding rate: **{fr:+.4f}%** — {bias}" if fr is not None else "- Perp funding: n/a",
            f"- Mark price: {fund.get('mark_price')}  |  Index: {fund.get('index_price')}",
        ]
    if oi:
        lines.append(f"- Open interest: {oi.get('open_interest_btc')} BTC"
                     + (f" (30m change {oi.get('oi_change_30m_pct')}%)" if oi.get('oi_change_30m_pct') is not None else ""))
    if lsr:
        r = lsr["long_short_ratio"]
        lines.append(f"- Global long/short account ratio: **{r}** "
                     f"({'crowd net long' if r > 1 else 'crowd net short'})")
    extra = get_coinalyze(coinalyze_key)
    if extra:
        lines.append(f"- Coinalyze (aggregated): {extra['coinalyze']}")
    if len(lines) <= 2:
        lines.append("- (No derivatives data available right now.)")
    lines += [
        "",
        "_Interpretation: extreme funding + rising OI often precedes mean-reverting "
        "squeezes; neutral funding with flat OI favors range/continuation. Weigh against "
        "the technical trend and the contract's implied probability._",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(build_fundamentals_report())
