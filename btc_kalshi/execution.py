"""btc_kalshi.execution — turn the agents' 5-tier rating into a Kalshi order.

Keeps TradingAgents' rating scale exactly (BUY / OVERWEIGHT / HOLD / UNDERWEIGHT
/ SELL) and maps it to the binary contract:

    BUY        -> buy YES (up), full conviction
    OVERWEIGHT -> buy YES (up), half conviction
    HOLD       -> no trade
    UNDERWEIGHT-> buy NO (down), half conviction
    SELL       -> buy NO (down), full conviction

Sizing is a fraction of balance scaled by conviction, capped by
max_contracts_per_trade. Orders are marketable limits at the ask (fills like a
market order) via the ported CandleKiller kalshi.place_order. dry_run=True by
default — nothing hits the exchange unless buying is explicitly enabled.
"""
from __future__ import annotations

import math

from . import kalshi, config as cfg

_CONVICTION = {"BUY": 1.0, "OVERWEIGHT": 0.5, "HOLD": 0.0, "UNDERWEIGHT": 0.5, "SELL": 1.0}
_SIDE = {"BUY": "yes", "OVERWEIGHT": "yes", "UNDERWEIGHT": "no", "SELL": "no"}


def normalize_rating(raw: str) -> str:
    r = (raw or "").strip().upper()
    for token in ("BUY", "OVERWEIGHT", "UNDERWEIGHT", "SELL", "HOLD"):
        if token in r:
            return token
    return "HOLD"


def plan_order(rating: str, contract: dict, balance: float | None) -> dict:
    """Decide what to do — no side effects. Returns a plan dict."""
    c = cfg.load_config()
    rating = normalize_rating(rating)
    conviction = _CONVICTION.get(rating, 0.0)

    if conviction == 0.0 or not contract:
        return {"action": "hold", "rating": rating, "reason": "rating=HOLD or no contract"}

    side = _SIDE[rating]
    ask = contract.get("yes_ask") if side == "yes" else contract.get("no_ask")
    if ask is None or ask <= 0:
        return {"action": "hold", "rating": rating, "side": side,
                "reason": f"no ask price for {side}"}

    # edge gate: skip if there's basically no payoff room left
    min_edge = float(c.get("min_ev_edge", 0.0) or 0.0)
    if ask >= (1.0 - max(min_edge, 0.01)):
        return {"action": "hold", "rating": rating, "side": side, "ask": ask,
                "reason": f"{side} ask {ask} too expensive (edge gate {min_edge})"}

    # sizing — fraction of balance scaled by conviction, capped by max_exposure ($)
    frac = float(c.get("wager_pct", c.get("kelly_fraction", 0.10)) or 0.10)
    max_exposure = float(c.get("max_exposure", 0) or 0)   # 0 = no dollar cap
    if balance and balance > 0:
        stake = balance * frac * conviction
    else:
        stake = float(c.get("min_bet", 1) or 1) * ask
    if max_exposure > 0:
        stake = min(stake, max_exposure)
    count = int(math.floor(stake / ask)) if ask > 0 else 0
    count = max(0, count)
    if count == 0:
        return {"action": "hold", "rating": rating, "side": side, "ask": ask,
                "reason": "computed size = 0 (low balance / exposure cap)"}

    return {
        "action": "buy", "rating": rating, "side": side, "count": count,
        "price_dollars": round(float(ask), 4), "ticker": contract.get("ticker"),
        "strike": contract.get("strike"), "mins_remaining": contract.get("mins_remaining"),
        "reason": f"{rating} -> buy {count} {side.upper()} @ {ask}",
    }


def execute(plan: dict, dry_run: bool = True) -> dict:
    """Execute a plan via the ported Kalshi layer. dry_run leaves the exchange alone."""
    if plan.get("action") != "buy":
        return {**plan, "executed": False}
    if dry_run:
        return {**plan, "executed": False, "dry_run": True}
    res = kalshi.place_order(plan["ticker"], plan["side"], plan["count"], plan["price_dollars"])
    return {**plan, "executed": "error" not in res, "kalshi_response": res}


def decide_and_execute(rating: str, contract: dict, dry_run: bool = True) -> dict:
    bal = kalshi.get_balance()
    plan = plan_order(rating, contract, bal)
    plan["balance_usd"] = bal
    return execute(plan, dry_run=dry_run)


# ── position-aware path: open / close / flip / hold (all five actions) ─────────
def held_position(positions: list, ticker: str) -> tuple[str | None, int]:
    """From kalshi.get_positions(): signed 'position' (>0 long YES, <0 long NO)."""
    for p in positions or []:
        if p.get("ticker") == ticker:
            n = int(p.get("position", 0) or 0)
            if n > 0:
                return "yes", n
            if n < 0:
                return "no", abs(n)
    return None, 0


def plan_action(rating: str, contract: dict, balance: float | None, positions: list) -> dict:
    """Decide the full action given what we already hold — no side effects.
    Returns one of: open / close_then_open / hold_position / hold."""
    rating = normalize_rating(rating)
    ticker = contract.get("ticker")
    side_held, count_held = held_position(positions, ticker)
    target = _SIDE.get(rating)  # 'yes' | 'no' | None(HOLD)

    # HOLD: keep any open position to settlement, otherwise stay flat
    if target is None:
        if side_held:
            return {"action": "hold_position", "held_side": side_held, "count": count_held,
                    "rating": rating, "reason": f"HOLD — let {count_held} {side_held.upper()} ride to settle"}
        return {"action": "hold", "rating": rating, "reason": "HOLD — flat"}

    # Already holding the SAME side -> don't stack
    if side_held == target:
        return {"action": "hold_position", "held_side": side_held, "count": count_held,
                "rating": rating, "reason": f"already long {count_held} {target.upper()}; not adding"}

    # Holding the OPPOSITE side -> sell to close, then open the new direction (flip)
    if side_held and side_held != target:
        bid = contract.get("yes_bid") if side_held == "yes" else contract.get("no_bid")
        return {"action": "close_then_open", "rating": rating,
                "close_side": side_held, "close_count": count_held,
                "close_price": round(float(bid), 4) if bid else None,
                "open": plan_order(rating, contract, balance),
                "reason": f"flip: sell {count_held} {side_held.upper()} -> buy {target.upper()}"}

    # Flat -> open
    return {"action": "open", "rating": rating, "open": plan_order(rating, contract, balance),
            "reason": "flat -> open"}


def manage_and_execute(rating: str, contract: dict, dry_run: bool = True) -> dict:
    """Position-aware execute: handles buy YES / buy NO / sell-to-close / flip / hold."""
    bal = kalshi.get_balance()
    positions = kalshi.get_positions()
    plan = plan_action(rating, contract, bal, positions)
    plan["balance_usd"] = bal
    if dry_run:
        return {**plan, "executed": False, "dry_run": True}

    results = {}
    if plan["action"] == "close_then_open":
        if plan.get("close_price"):
            results["close"] = kalshi.place_sell_order(
                contract["ticker"], plan["close_side"], plan["close_count"], plan["close_price"])
        op = plan["open"]
        if op.get("action") == "buy":
            results["open"] = kalshi.place_order(
                op["ticker"], op["side"], op["count"], op["price_dollars"])
    elif plan["action"] == "open":
        op = plan["open"]
        if op.get("action") == "buy":
            results["open"] = kalshi.place_order(
                op["ticker"], op["side"], op["count"], op["price_dollars"])
    # hold / hold_position -> no exchange action
    return {**plan, "executed": True, "kalshi": results}
