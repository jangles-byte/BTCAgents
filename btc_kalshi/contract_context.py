"""btc_kalshi.contract_context — the live Kalshi contract the agents are betting on.

Each loop the bot needs exactly three things (your words): current up/down price,
the strike, and time left. This wraps kalshi.get_front_market() into a context
block that gets injected into the Trader and Portfolio Manager prompts, plus the
implied probability so the decision is priced against the market (edge), not made
in a vacuum.
"""
from __future__ import annotations

from . import kalshi


def get_contract() -> dict | None:
    """The active KXBTC15M market (nearest close). See kalshi.get_front_market()."""
    return kalshi.get_front_market()


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
        "_Decision rule: only take YES if your edge says P(up) is meaningfully ABOVE "
        "the YES ask; only take NO if P(up) is meaningfully BELOW (1 - NO ask). "
        "Otherwise HOLD — there is no edge in paying the spread._",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(build_contract_context())
