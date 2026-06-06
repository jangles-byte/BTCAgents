"""btc_kalshi.ta_crypto_vendor — register a 'crypto' data vendor INTO TradingAgents
at runtime, without editing any TradingAgents file.

TradingAgents routes every data call through interface.VENDOR_METHODS[method][vendor].
We add vendor="crypto" implementations that return BTC market data / derivatives
positioning instead of stock data. Select it via data_vendors in the config
(settings.build_ta_config does this). News stays on yfinance/alpha_vantage so the
news + sentiment agents keep working, exactly as you asked.

Call register_crypto_vendor() once before building the graph (the runner does this).
"""
from __future__ import annotations

from . import crypto_data, crypto_fundamentals, contract_context, settings

# Active Kalshi contract for the current loop — set by the runner so the Market
# Analyst's price snapshot includes the live strike / minutes-left / implied prob.
_ACTIVE_CONTRACT: dict | None = None


def set_active_contract(contract: dict | None) -> None:
    global _ACTIVE_CONTRACT
    _ACTIVE_CONTRACT = contract


# ── vendor implementations (must match TradingAgents tool signatures) ──────────
def _crypto_stock_data(symbol, start_date, end_date):
    m = _ACTIVE_CONTRACT or {}
    report = crypto_data.build_market_report(
        strike=m.get("strike"), mins_remaining=m.get("mins_remaining"))
    if m:
        report += "\n\n" + contract_context.build_contract_context(m)
    return report


def _crypto_indicators(symbol, indicator, curr_date, look_back_days=30):
    k = crypto_data.get_klines("1m", 60)
    f = crypto_data.compute_features(k)
    if not f:
        return f"No crypto indicator data available for '{indicator}'."
    ind = (indicator or "").lower()
    pick = {
        "rsi": f"RSI(14,1m) = {f.get('rsi_14')}",
        "macd": f"EMA9 {f.get('ema9')} vs EMA21 {f.get('ema21')} -> trend {f.get('ema_trend')}",
        "ema": f"EMA9 {f.get('ema9')} / EMA21 {f.get('ema21')} ({f.get('ema_trend')})",
        "close": f"Last close = {f.get('last')}",
        "atr": f"1m realized vol (pct stdev) = {f.get('vol_1m_pct')}",
        "volume": f"Volume last {f.get('vol_last')} vs 20-avg {f.get('vol_avg')}",
    }
    for key, txt in pick.items():
        if key in ind:
            return txt
    # default: full snapshot
    return (f"BTC 1m features — last {f.get('last')}, RSI {f.get('rsi_14')}, "
            f"trend {f.get('ema_trend')}, ret_5m {f.get('ret_5m')}%, "
            f"vol {f.get('vol_1m_pct')}")


def _crypto_fundamentals(symbol, *a, **k):
    return crypto_fundamentals.build_fundamentals_report(settings.coinalyze_key())


def _na(label):
    def f(*a, **k):
        return (f"{label} is not applicable to BTC (no issuer financials). "
                "See the positioning & flows report for the BTC-relevant fundamentals.")
    return f


def register_crypto_vendor() -> None:
    """Inject crypto implementations into TradingAgents' vendor table."""
    from tradingagents.dataflows import interface

    reg = {
        "get_stock_data": _crypto_stock_data,
        "get_indicators": _crypto_indicators,
        "get_fundamentals": _crypto_fundamentals,
        "get_balance_sheet": _na("Balance sheet"),
        "get_cashflow": _na("Cash flow statement"),
        "get_income_statement": _na("Income statement"),
    }
    for method, impl in reg.items():
        interface.VENDOR_METHODS.setdefault(method, {})["crypto"] = impl
    if "crypto" not in interface.VENDOR_LIST:
        interface.VENDOR_LIST.append("crypto")
