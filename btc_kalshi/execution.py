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


def open_exposure(positions: list) -> float:
    """Total $ currently deployed across open positions (your 'money out')."""
    tot = 0.0
    for p in positions or []:
        n = abs(int(p.get("position", 0) or 0))
        if not n:
            continue
        me = p.get("market_exposure")
        if me is not None:
            try:
                tot += float(me) / 100.0
                continue
            except (TypeError, ValueError):
                pass
        tot += n * 0.5  # fallback if Kalshi didn't return a cost field
    return tot


def plan_order(rating: str, contract: dict, balance: float | None,
               positions: list | None = None) -> dict:
    """Decide what to do — no side effects. Sizing is %-of-account-equity based so
    it scales as the balance grows, and TOTAL open exposure (money out across all
    positions) is capped at a % of equity — not a hard per-trade dollar amount."""
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

    max_entry = float(c.get("max_entry_price") or 0.90)
    if ask > max_entry:
        return {"action": "hold", "rating": rating, "side": side, "ask": ask,
                "reason": f"{side.upper()} ask {ask:.2f} > max entry {max_entry:.2f} — no payoff, skip"}

    # ── %-of-equity sizing + total-exposure cap (both scale with the account) ──
    bal = float(balance or 0.0)
    exposure = open_exposure(positions)
    equity = bal + exposure                                   # total account value
    wager_pct = float(c.get("wager_pct") or 0.10)             # per-trade % of equity
    max_exp_pct = float(c.get("max_exposure_pct") or 0.50)    # max % deployed at once
    room = max(0.0, max_exp_pct * equity - exposure)          # new exposure allowed ($)
    if room <= 0:
        return {"action": "hold", "rating": rating, "side": side, "ask": ask,
                "reason": f"exposure cap hit: {max_exp_pct*100:.0f}% of ${equity:.0f} already deployed"}
    stake = min(wager_pct * equity * conviction, room)
    if bal > 0:
        stake = min(stake, bal)                               # can't spend more cash than we have
    count = int(math.floor(stake / ask)) if ask > 0 else 0
    if count <= 0:
        return {"action": "hold", "rating": rating, "side": side, "ask": ask,
                "reason": f"computed size 0 (stake ${stake:.2f} / ask {ask:.2f})"}

    return {
        "action": "buy", "rating": rating, "side": side, "count": count,
        "price_dollars": round(float(ask), 4), "ticker": contract.get("ticker"),
        "strike": contract.get("strike"), "mins_remaining": contract.get("mins_remaining"),
        "reason": f"{rating} -> buy {count} {side.upper()} @ {ask} "
                  f"(stake ${stake:.0f} of ${equity:.0f} equity)",
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
                "open": plan_order(rating, contract, balance, positions),
                "reason": f"flip: sell {count_held} {side_held.upper()} -> buy {target.upper()}"}

    # Flat -> open
    return {"action": "open", "rating": rating,
            "open": plan_order(rating, contract, balance, positions),
            "reason": "flat -> open"}


def _order_fields(plan: dict):
    op = plan.get("open") if isinstance(plan.get("open"), dict) else None
    src = op or plan
    return src.get("side"), src.get("count"), src.get("price_dollars")


def manage_and_execute(rating: str, contract: dict, dry_run: bool = True) -> dict:
    """Position-aware execute. Returns FLAT fields so the log + dashboard show the
    real outcome: side, count, price, and `placed` (did an order actually go)."""
    bal = kalshi.get_balance()
    positions = kalshi.get_positions()
    plan = plan_action(rating, contract, bal, positions)
    side, count, price = _order_fields(plan)

    op = plan.get("open") if isinstance(plan.get("open"), dict) else None
    wants_order = plan["action"] in ("open", "close_then_open") and op and op.get("action") == "buy"
    action, reason = plan["action"], plan.get("reason")
    if plan["action"] in ("open", "close_then_open") and not wants_order:
        # plan_order declined (too expensive / size 0) -> surface that honestly
        action, reason = "hold", (op or {}).get("reason", reason)

    out = {"action": action, "rating": plan.get("rating"), "reason": reason,
           "side": side, "count": count, "price_dollars": price, "balance_usd": bal,
           "ticker": contract.get("ticker"), "strike": contract.get("strike"),
           "mins_remaining": contract.get("mins_remaining"), "placed": False, "dry_run": dry_run}

    if dry_run or not wants_order:
        return out

    # The cycle took minutes, so the price from cycle-start is stale. Re-fetch the
    # live ask and place a MARKETABLE limit (cross the spread a touch) so the order
    # actually FILLS instead of resting unfilled until the contract settles.
    side = op["side"]
    ask = op["price_dollars"]
    try:
        fresh = kalshi.get_front_market(0)
        if fresh and fresh.get("ticker") == op["ticker"]:
            a = fresh.get("yes_ask") if side == "yes" else fresh.get("no_ask")
            if a:
                ask = float(a)
    except Exception:
        pass
    buf = float(cfg.load_config().get("marketable_buffer") or 0.03)
    price = min(0.99, round(float(ask) + buf, 2))
    out["price_dollars"] = price

    if plan["action"] == "close_then_open" and plan.get("close_price"):
        out["close"] = kalshi.place_sell_order(
            contract["ticker"], plan["close_side"], plan["close_count"], plan["close_price"])
    res = kalshi.place_order(op["ticker"], side, op["count"], price)
    out["placed"] = "error" not in res
    if "error" in res:
        out["error"] = res["error"]
    else:
        o = res.get("order", {}) if isinstance(res, dict) else {}
        out["order_status"] = o.get("status")
        out["order_id"] = o.get("order_id")
        # ground truth: did we actually end up in a position on this ticker?
        try:
            import time as _t
            _t.sleep(0.4)
            s2, c2 = held_position(kalshi.get_positions(), op["ticker"])
            out["after_position"] = (f"{s2} x{c2}" if s2 else "flat (order did not fill)")
            # take-profit: rest a GTC sell at the configured price on the side we now hold
            tp = cfg.load_config().get("take_profit_price")
            if tp and s2 and c2 > 0:
                tpf = float(tp)
                if tpf > 1:
                    tpf /= 100.0          # accept "97" or "0.97"
                out["take_profit_at"] = round(tpf, 4)
                out["take_profit"] = kalshi.place_sell_order(op["ticker"], s2, c2, round(tpf, 4))
        except Exception:
            pass
    return out
