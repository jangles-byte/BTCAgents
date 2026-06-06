"""btc_kalshi.fast_decide — ONE fast LLM pass for the 15-minute up/down call.

The full TradingAgents debate (~8 sequential agents writing essays) is too slow
for a 15-minute market — a cycle often can't finish before the contract expires.
This makes a SINGLE streaming LLM call over the same data (price, real indicators,
funding/OI, the live contract) so you see the full reasoning in the log and it
finishes in seconds. Falls back to a deterministic spot-vs-strike call on error.
"""
from __future__ import annotations

import re

from . import crypto_data, contract_context, settings, config as cfg


def _llm():
    from tradingagents.llm_clients import create_llm_client
    c = cfg.load_config()
    model = c.get("quick_think_llm") or c.get("deep_think_llm") or "claude-haiku-4-5"
    client = create_llm_client(provider=c.get("llm_provider", "anthropic"),
                               model=model, base_url=c.get("ollama_url") or None)
    return client.get_llm()


def decide(contract: dict):
    """Return (rating, reasoning_text). Streams the reasoning to stdout (the log)."""
    settings.apply_env()
    strike = contract.get("strike")
    mins = contract.get("mins_remaining")
    report = crypto_data.build_market_report(strike=strike, mins_remaining=mins)
    ctx = contract_context.build_contract_context(contract)

    system = ("You are a decisive short-term trader betting whether BTC will close ABOVE or "
              "BELOW a strike price within the next few minutes on Kalshi (a binary up/down "
              "market). Use ONLY short-term price action, momentum, volatility and the "
              "contract's implied probability. Ignore long-term macro and multi-week targets. "
              "Be concise and commit to a direction.")
    user = (f"{report}\n\n{ctx}\n\n"
            f"Reason in 4-7 short sentences about the next {mins} minutes, then end with "
            f"EXACTLY these two lines:\n"
            f"DECISION: BUY   (you expect BTC ABOVE the strike at close / up)\n"
            f"  — or — DECISION: SELL (below / down)  — or — DECISION: HOLD (only a true coin-flip)\n"
            f"CONFIDENCE: <0-100>")
    msgs = [("system", system), ("human", user)]

    text = ""
    print("\n----- fast 15-min decision (single LLM pass) -----", flush=True)
    try:
        for ch in _llm().stream(msgs):
            piece = getattr(ch, "content", "") or ""
            if isinstance(piece, list):
                piece = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in piece)
            print(piece, end="", flush=True)
            text += piece
        print("\n--------------------------------------------------", flush=True)
    except Exception as e:
        print(f"\n[fast_decide error: {e} — falling back to spot vs strike]", flush=True)
        spot = crypto_data.get_spot()
        if spot and strike:
            return ("BUY" if spot >= strike else "SELL"), f"fallback: spot {spot} vs strike {strike}"
        return "HOLD", "fallback: no data"

    m = re.search(r"DECISION:\s*\**\s*(BUY|SELL|HOLD|UP|DOWN)", text, re.I)
    raw = (m.group(1).upper() if m else "HOLD")
    rating = {"UP": "BUY", "DOWN": "SELL"}.get(raw, raw)
    return rating, text
