# BTCAgents — TradingAgents, pointed at Kalshi BTC up/down (15-min)

This is [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
kept **as-built** (same analyst → bull/bear debate → trader → risk debate →
portfolio manager, same 5-tier rating, same memory/reflection) with one change:
**the order routes to Kalshi instead of a stock broker.** The Kalshi layer is
lifted verbatim from CandleKiller (the one part of it that works).

Nothing in `tradingagents/` was edited. All new code lives in `btc_kalshi/` and
`config_app/`, and the crypto data vendor registers itself into TradingAgents at
runtime.

## What was added

```
btc_kalshi/
  kalshi.py            # ported from CandleKiller — RSA-PSS auth, place/sell/positions/balance/settlements
  config.py            # ported — bot_config.json I/O + account routing (acct1 REAL, acct2 DEMO)
  crypto_data.py       # BTC spot/OHLCV/indicators (Coinbase→Kraken→Binance fallback)
  crypto_fundamentals.py # funding / open interest / long-short (the BTC "fundamentals")
  contract_context.py  # live KXBTC15M: yes/no price, strike, minutes left, implied prob
  ta_crypto_vendor.py  # registers a "crypto" vendor INTO TradingAgents (no core edits)
  settings.py          # bot_config.json -> env vars + TradingAgents config
  execution.py         # 5-tier rating -> Kalshi order (BUY/OW->YES, SELL/UW->NO, conviction->size)
  runner.py            # the loop: contract -> agent debate -> rating -> order -> repeat
config_app/
  app.py + templates/  # config page: stores every key, masks secrets, "Test Kalshi" button
```

## Account model (verbatim from CandleKiller — both endpoints)

- **Account 1 = REAL** → `https://api.elections.kalshi.com/trade-api/v2`
- **Account 2 = DEMO** → `https://external-api.demo.kalshi.co/trade-api/v2`
- **Market data always reads from production**, so prices are real no matter which
  account trades. `active_account` (1 or 2) decides where orders/balance go.

## Rating → Kalshi mapping

| TradingAgents rating | Kalshi action            |
|----------------------|--------------------------|
| BUY                  | buy YES (up), full size  |
| OVERWEIGHT           | buy YES (up), half size  |
| HOLD                 | no trade                 |
| UNDERWEIGHT          | buy NO (down), half size |
| SELL                 | buy NO (down), full size |

Size = `wager_pct × conviction × balance`, capped by `max_contracts_per_trade`.
An edge gate skips trades where the ask leaves no payoff room.

## Setup

```bash
cd ~/Desktop/BTCAgents
python3 -m venv venv && source venv/bin/activate
pip install .                       # installs TradingAgents + deps (pyproject.toml)
pip install -r requirements_btc.txt # flask, requests, cryptography (glue + config page)
```

## 1) Configure (the config page)

```bash
python -m config_app.app      # → http://127.0.0.1:5057
```

Enter Kalshi account 1 + 2 keys, pick the active account (start on **2 = demo**),
add your LLM provider key, then click **Test Kalshi connection** — you should see
your balance and the live KXBTC15M market. Optional keys are marked *(optional)*.

## 2) Validate the plumbing (no LLM, no cost)

```bash
python -m btc_kalshi.runner --smoke
```

Shows the live contract, balance, what the Market/Fundamentals analysts will
receive, and what a BUY/HOLD/SELL would do.

## 3) Run

```bash
python -m btc_kalshi.runner --once     # one full agent cycle (uses your LLM key)
python -m btc_kalshi.runner            # continuous loop
```

**Trades are DRY-RUN until you set `buying_enabled: true` in the config.** Start on
the demo account, confirm orders land, then switch to real.

## Notes
- The original TradingAgents CLI (`python -m cli.main`) still works for stocks —
  nothing was removed.
- News/sentiment agents keep using yfinance/reddit (still useful for BTC headlines).
- A broken `.git/` from the initial clone may be present; delete it for a clean repo.
