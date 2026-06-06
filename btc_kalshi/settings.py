"""btc_kalshi.settings — bridge between the config page (bot_config.json) and
TradingAgents (which reads env vars + a config dict).

apply_env()      -> push API keys from bot_config.json into os.environ so the
                    untouched TradingAgents code finds them.
build_ta_config()-> a DEFAULT_CONFIG copy with the user's provider/model choices,
                    and our crypto data vendor selected.
"""
from __future__ import annotations

import os

from . import config as cfg

# Map config.json field -> environment variable TradingAgents/LLM clients expect.
_ENV_MAP = {
    "openai_api_key": "OPENAI_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "claude_api_key": "ANTHROPIC_API_KEY",   # CandleKiller called it claude_api_key
    "google_api_key": "GOOGLE_API_KEY",
    "xai_api_key": "XAI_API_KEY",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "alpha_vantage_api_key": "ALPHA_VANTAGE_API_KEY",
    "finnhub_api_key": "FINNHUB_API_KEY",
    "reddit_client_id": "REDDIT_CLIENT_ID",
    "reddit_client_secret": "REDDIT_CLIENT_SECRET",
    "reddit_user_agent": "REDDIT_USER_AGENT",
}


def apply_env() -> None:
    """Load secrets from bot_config.json into the process environment."""
    c = cfg.load_config()
    for field, env in _ENV_MAP.items():
        val = c.get(field)
        if val and not str(val).startswith("•") and not os.getenv(env):
            os.environ[env] = str(val)


def coinalyze_key() -> str | None:
    return cfg.load_config().get("coinalyze_api_key") or None


def build_ta_config() -> dict:
    """A TradingAgents config reflecting the user's provider/model picks + our
    crypto data vendor. Imported lazily so this module loads without the package."""
    from tradingagents.default_config import DEFAULT_CONFIG

    c = cfg.load_config()
    ta = DEFAULT_CONFIG.copy()
    ta["llm_provider"] = c.get("llm_provider", ta.get("llm_provider", "openai"))
    if c.get("deep_think_llm"):
        ta["deep_think_llm"] = c["deep_think_llm"]
    if c.get("quick_think_llm"):
        ta["quick_think_llm"] = c["quick_think_llm"]
    if c.get("ollama_url"):
        ta["backend_url"] = c["ollama_url"]
    if c.get("max_debate_rounds") is not None:
        ta["max_debate_rounds"] = int(c["max_debate_rounds"])
    # Route the data vendors at our crypto layer (handled in the graph wiring step).
    ta.setdefault("data_vendors", {})
    ta["data_vendors"]["core_stock_apis"] = "crypto"
    ta["data_vendors"]["technical_indicators"] = "crypto"
    ta["data_vendors"]["fundamental_data"] = "crypto"
    # news_data stays on yfinance (keeps the news + sentiment agents working for BTC)
    ta["asset_class"] = "crypto"
    return ta
