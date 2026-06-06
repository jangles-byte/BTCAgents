"""btc_kalshi.runner — the loop.

Your spec: it just runs, decides buy/sell/hold, acts, and runs again — over and
over. Each pass it pulls the live KXBTC15M contract (up/down price, strike, time
left), runs the full TradingAgents debate on BTC, maps the rating to a Kalshi
order, executes (on the active account: 1=real, 2=demo), then loops.

Modes:
    python -m btc_kalshi.runner --smoke      # no LLM: prove the plumbing works
    python -m btc_kalshi.runner --once       # one full agent cycle (needs LLM key)
    python -m btc_kalshi.runner              # continuous loop
Safety: trades are DRY-RUN unless buying_enabled=true in bot_config.json.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from . import settings, contract_context, execution, kalshi, config as cfg
from . import ta_crypto_vendor, crypto_data, crypto_fundamentals, logstore


def _now():
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _buying_enabled() -> bool:
    return str(cfg.load_config().get("buying_enabled", False)).lower() in ("1", "true", "yes")


def smoke() -> None:
    """Exercise everything except the LLM graph — safe, no keys, no tokens."""
    print(f"[{_now()}] SMOKE — validating plumbing (no LLM calls)\n")
    ta_crypto_vendor.register_crypto_vendor()

    c = contract_context.get_contract()
    print("Front KXBTC15M contract:")
    print("  ", c if c else "None (check Kalshi credentials in the config page)")
    bal = kalshi.get_balance()
    print("Active-account balance:", bal)

    ta_crypto_vendor.set_active_contract(c)
    print("\n--- Market Analyst would receive: ---")
    print(crypto_data.build_market_report(
        strike=(c or {}).get("strike"), mins_remaining=(c or {}).get("mins_remaining"))[:600])
    print("\n--- Fundamentals Analyst would receive: ---")
    print(crypto_fundamentals.build_fundamentals_report(settings.coinalyze_key())[:400])

    if c:
        for r in ("BUY", "HOLD", "SELL"):
            print(f"\nIf rating={r}: ", execution.plan_order(r, c, bal))
    print("\nSmoke complete. Add keys in the config page, then run --once.")


def run_once(dry_run: bool | None = None) -> dict:
    """One full cycle: contract -> agent debate -> rating -> order."""
    settings.apply_env()
    ta_crypto_vendor.register_crypto_vendor()
    from tradingagents.graph.trading_graph import TradingAgentsGraph  # lazy: needs TA deps

    min_mins = float(cfg.load_config().get("candle_min_minutes") or 4)
    contract = contract_context.get_contract(min_minutes=min_mins)
    if not contract:
        print(f"[{_now()}] no KXBTC15M market with >= {min_mins:g}m left; skipping.")
        logstore.set_status("idle", note=f"waiting for a market with >= {min_mins:g}m left")
        return {"action": "skip", "reason": "no fresh contract"}
    ta_crypto_vendor.set_active_contract(contract)
    logstore.set_status("analyzing", started=time.time(), ticker=contract.get("ticker"),
                        strike=contract.get("strike"), mins_remaining=contract.get("mins_remaining"))

    graph = TradingAgentsGraph(debug=True, config=settings.build_ta_config())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"[{_now()}] running agents on {contract['ticker']} "
          f"(strike {contract['strike']}, {contract['mins_remaining']}m left)…")
    _, decision = graph.propagate("BTC-USD", today)

    # wallet floor: auto-disable buying once balance falls to/below the floor
    floor = float(cfg.load_config().get("wallet_floor") or 0)
    bal = kalshi.get_balance()
    if _buying_enabled() and floor > 0 and bal is not None and bal <= floor:
        cfg.update_config(buying_enabled=False)
        print(f"[{_now()}] wallet floor ${floor} reached (balance ${bal}) — buying disabled.")

    if dry_run is None:
        dry_run = not _buying_enabled()
    result = execution.manage_and_execute(str(decision), contract, dry_run=dry_run)
    try:
        logstore.append_decision({**result, "ticker": contract.get("ticker"),
                                  "strike": contract.get("strike"),
                                  "mins_remaining": contract.get("mins_remaining")})
    except Exception:
        pass
    print(f"[{_now()}] rating={result.get('rating')} action={result.get('action')} "
          f"placed={result.get('placed')} side={result.get('side')} count={result.get('count')} "
          f"@ {result.get('price_dollars')} status={result.get('order_status')} "
          f"after={result.get('after_position')} -> {result.get('reason')}"
          + (f"  ERROR={result.get('error')}" if result.get('error') else ""))
    logstore.set_status("idle", last_done=time.time(), last_rating=result.get("rating"),
                        last_action=result.get("action"))
    return result


def loop(interval_sec: int = 60) -> None:
    print(f"[{_now()}] BTCAgents loop started. buying_enabled={_buying_enabled()} "
          f"(dry-run until enabled). Ctrl-C to stop.\n")
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            print("\nstopped."); break
        except Exception as e:
            print(f"[{_now()}] cycle error: {e}")
            logstore.set_status("error", error=str(e)[:200])
        time.sleep(interval_sec)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="validate plumbing, no LLM")
    ap.add_argument("--once", action="store_true", help="one full agent cycle")
    ap.add_argument("--interval", type=int, default=60, help="seconds between cycles")
    args = ap.parse_args()
    if args.smoke:
        smoke()
    elif args.once:
        run_once()
    else:
        loop(args.interval)
