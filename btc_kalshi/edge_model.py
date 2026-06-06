"""btc_kalshi.edge_model — quantitative fair-value edge for the 15-min binary.

Predicting BTC up/down in 15 minutes is ~a coin flip, and Kalshi prices it about
fairly plus a spread, so betting a direction every cycle just bleeds the spread.
The only way to be +EV is to bet ONLY when our fair probability of the outcome
beats the PRICE WE PAY by a margin.

This computes P(close ABOVE strike) from spot-vs-strike, recent 1-minute realized
volatility and the minutes remaining (normal model, ~zero drift over 15 min),
compares it to the live ask we'd actually pay, and trades only when the edge
exceeds `min_ev_edge` (which must cover the spread). No edge -> HOLD.
"""
from __future__ import annotations

import math

from . import crypto_data, kalshi, config as cfg


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fair_prob_up(spot, strike, mins, vol_1m_pct) -> float | None:
    """P(close above strike) ~ Normal( (spot-strike) / (sigma*sqrt(mins)) )."""
    if not spot or not strike or not vol_1m_pct or mins is None or mins <= 0:
        return None
    sigma = spot * (float(vol_1m_pct) / 100.0) * math.sqrt(max(float(mins), 0.05))  # $ stdev
    if sigma <= 0:
        return None
    return _ncdf((float(spot) - float(strike)) / sigma)


def decide(contract: dict):
    """Return (rating, reasoning). Bets only when fair prob beats the ask by edge."""
    c = cfg.load_config()
    spot = crypto_data.get_spot()
    feats = crypto_data.compute_features(crypto_data.get_klines("1m", 60)) or {}
    vol = feats.get("vol_1m_pct")
    strike = contract.get("strike")
    mins = contract.get("mins_remaining")
    p_up = fair_prob_up(spot, strike, mins, vol)

    # the prices we ACTUALLY pay live on the demo book; fall back to the contract's
    # production asks if the demo quote is unavailable.
    q = kalshi.get_active_quote(contract.get("ticker")) or {}
    yes_ask = q.get("yes_ask") if q.get("yes_ask") is not None else contract.get("yes_ask")
    no_ask = q.get("no_ask") if q.get("no_ask") is not None else contract.get("no_ask")
    min_edge = float(c.get("min_ev_edge") or 0.04)

    head = (f"fair P(up)={p_up:.3f}" if p_up is not None else "fair P(up)=n/a")
    msg = (f"{head} | spot {spot} strike {strike} {mins}m vol {vol} | "
           f"YES ask {yes_ask} NO ask {no_ask} | min_edge {min_edge}")
    print("\n----- edge model -----\n" + msg, flush=True)

    if p_up is None or yes_ask is None or no_ask is None:
        print(" -> HOLD (missing data)", flush=True)
        return "HOLD", msg + " | HOLD (missing data)"

    yes_edge = p_up - float(yes_ask)            # value in buying YES (up)
    no_edge = (1.0 - p_up) - float(no_ask)      # value in buying NO (down)
    if yes_edge >= min_edge and yes_edge >= no_edge:
        print(f" -> BUY  (YES underpriced, edge {yes_edge:+.3f})", flush=True)
        return "BUY", msg + f" | BUY YES edge {yes_edge:+.3f}"
    if no_edge >= min_edge:
        print(f" -> SELL (NO underpriced, edge {no_edge:+.3f})", flush=True)
        return "SELL", msg + f" | SELL NO edge {no_edge:+.3f}"
    print(f" -> HOLD (no edge: YES {yes_edge:+.3f}, NO {no_edge:+.3f})", flush=True)
    return "HOLD", msg + f" | HOLD (YES {yes_edge:+.3f}, NO {no_edge:+.3f})"
