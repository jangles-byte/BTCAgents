"""btc_kalshi.contract_context — the live Kalshi contract the agents are betting on.

Each loop the bot needs exactly three things (your words): current up/down price,
the strike, and time left. This wraps kalshi.get_front_market() into a context
block that gets injected into the Trader and Portfolio Manager prompts, plus the
implied probability so the decision is priced against the market (edge), not made
in a vacuum.
"""
from __future__ import annotations

from . import kalshi


def get_contract(min_minutes: float = 0.0) -> dict | None:
    """The active KXBTC15M market. Pass min_minutes to require enough time left
    to actually analyze and trade it. See kalshi.get_front_market()."""
    return kalshi.get_front_market(min_minutes)


def implied_prob(yes_ask: float | None, yes_bid: float | None) -> float | None:
    """Mid YES price ≈ market-implied probability of 'up'. Prices are in dollars (0–1)."""
    if yes_ask is not None and yes_bid is not None:
        return round((yes_ask + yes_bid) / 2, 4)
    return yes_ask if yes_ask is not None else yes_bid


def build_contract_context(contract: dict | None = None) -> str:
    """Markdown block describing the contract under decision."""
    m = contract or get_contract()
    if not m:
        return ("# Kalshi Contract\n- No open KXBTC15M market found (check credentials / "
                "market hours).")
    p = implied_prob(m.get("yes_ask"), m.get("yes_bid"))
    lines = [
        "# Kalshi Contract Under Decision (BTC up/down, 15-minute)",
        f"- Market ticker: `{m.get('ticker')}`",
        f"- Strike: **{m.get('strike')}**",
        f"- Time left: **{m.get('mins_remaining')} min**",
        f"- YES (up): ask {m.get('yes_ask')} / bid {m.get('yes_bid')}",
        f"- NO (down): ask {m.get('no_ask')} / bid {m.get('no_bid')}",
        f"- Market-implied P(up): **{p}**" if p is not None else "- Market-implied P(up): n/a",
        "",
        "_THIS IS A 15-MINUTE BET. Predict ONLY whether BTC will close ABOVE (YES/up) "
        "or BELOW (NO/down) the strike in the minutes shown above. Base the call on "
        "SHORT-TERM price action (last 1-15 min), distance to strike, momentum and "
        "volatility. IGNORE long-term macro, Fed policy, on-chain cycles and multi-week "
        "price targets — they are irrelevant on a 15-minute horizon. Conclude with a firm "
        "BUY (you expect UP) or SELL (you expect DOWN); only HOLD if it is a genuine "
        "coin-flip. Prefer the side that looks underpriced versus your prediction._",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(build_contract_context())
