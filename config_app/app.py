"""BTCAgents — Config page.

A single page that stores EVERY key the project can use, into bot_config.json
(the same file the Kalshi layer + agents read). Secrets are masked once saved and
only overwritten when you type a new value. Live "Test" buttons verify the Kalshi
connection (active account) without leaving the page.

Run:
    cd ~/Desktop/BTCAgents
    pip install -r requirements_btc.txt
    python -m config_app.app
    # open http://127.0.0.1:5057
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request

# make the project root importable (btc_kalshi package)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from btc_kalshi import config as cfg  # noqa: E402
from btc_kalshi import kalshi, crypto_data, crypto_fundamentals, contract_context, logstore, procman  # noqa: E402

app = Flask(__name__)

MASK = "••••••••"

# ── field schema: one entry per stored key ────────────────────────────────────
# type: text | password | textarea | number | select | radio
SECTIONS = [
    ("Kalshi — Account 1 (REAL · api.elections.kalshi.com)", [
        {"key": "kalshi_api_key_id", "label": "API Key ID", "type": "text", "secret": True},
        {"key": "kalshi_private_key_pem", "label": "Private Key (PEM, paste full key)",
         "type": "textarea", "secret": True},
        {"key": "kalshi_private_key_path", "label": "…or path to PEM file", "type": "text",
         "optional": True, "placeholder": "/Users/you/Desktop/kalshi_key.pem"},
    ]),
    ("Kalshi — Account 2 (DEMO · external-api.demo.kalshi.co)", [
        {"key": "kalshi_api_key_id_2", "label": "API Key ID", "type": "text", "secret": True,
         "optional": True},
        {"key": "kalshi_private_key_pem_2", "label": "Private Key (PEM)", "type": "textarea",
         "secret": True, "optional": True},
        {"key": "kalshi_private_key_path_2", "label": "…or path to PEM file", "type": "text",
         "optional": True},
        {"key": "kalshi_base_url_2", "label": "Demo base URL", "type": "text", "optional": True,
         "placeholder": "https://external-api.demo.kalshi.co/trade-api/v2"},
    ]),
    ("Active account", [
        {"key": "active_account", "label": "Trade with", "type": "radio",
         "choices": [("1", "Account 1 — REAL"), ("2", "Account 2 — DEMO")], "default": "2"},
    ]),
    ("LLM / Agents", [
        {"key": "llm_provider", "label": "Provider", "type": "select",
         "choices": [("openai", "OpenAI"), ("anthropic", "Anthropic"), ("google", "Google"),
                     ("xai", "xAI"), ("deepseek", "DeepSeek"), ("openrouter", "OpenRouter"),
                     ("ollama", "Ollama (local)")], "default": "openai"},
        {"key": "deep_think_llm", "label": "Deep-think model", "type": "text",
         "placeholder": "gpt-5.4"},
        {"key": "quick_think_llm", "label": "Quick-think model", "type": "text",
         "placeholder": "gpt-5.4-mini"},
        {"key": "max_debate_rounds", "label": "Debate rounds", "type": "number",
         "optional": True, "placeholder": "1"},
        {"key": "openai_api_key", "label": "OpenAI API key", "type": "password", "secret": True,
         "optional": True},
        {"key": "anthropic_api_key", "label": "Anthropic API key", "type": "password",
         "secret": True, "optional": True},
        {"key": "google_api_key", "label": "Google API key", "type": "password", "secret": True,
         "optional": True},
        {"key": "xai_api_key", "label": "xAI API key", "type": "password", "secret": True,
         "optional": True},
        {"key": "deepseek_api_key", "label": "DeepSeek API key", "type": "password",
         "secret": True, "optional": True},
        {"key": "openrouter_api_key", "label": "OpenRouter API key", "type": "password",
         "secret": True, "optional": True},
        {"key": "ollama_url", "label": "Ollama base URL", "type": "text", "optional": True,
         "placeholder": "http://localhost:11434/v1"},
    ]),
    ("Data sources (optional)", [
        {"key": "coinalyze_api_key", "label": "Coinalyze API key (funding/OI)",
         "type": "password", "secret": True, "optional": True},
        {"key": "alpha_vantage_api_key", "label": "Alpha Vantage API key", "type": "password",
         "secret": True, "optional": True},
        {"key": "finnhub_api_key", "label": "Finnhub API key", "type": "password",
         "secret": True, "optional": True},
        {"key": "reddit_client_id", "label": "Reddit client ID", "type": "text", "optional": True},
        {"key": "reddit_client_secret", "label": "Reddit client secret", "type": "password",
         "secret": True, "optional": True},
        {"key": "reddit_user_agent", "label": "Reddit user agent", "type": "text",
         "optional": True},
    ]),
    ("Risk & sizing", [
        {"key": "max_exposure", "label": "Max exposure ($ per trade)", "type": "number",
         "placeholder": "100"},
        {"key": "wallet_floor", "label": "Wallet floor ($ — buying stops at this balance)",
         "type": "number", "placeholder": "50"},
        {"key": "wager_pct", "label": "Wager fraction of balance", "type": "number",
         "optional": True, "placeholder": "0.10"},
        {"key": "kelly_fraction", "label": "Kelly fraction", "type": "number", "optional": True,
         "placeholder": "0.25"},
        {"key": "min_ev_edge", "label": "Min edge to trade (prob)", "type": "number",
         "optional": True, "placeholder": "0.04"},
    ]),
]

SECRET_KEYS = {f["key"] for _, fields in SECTIONS for f in fields if f.get("secret")}


def _view_config() -> dict:
    """Current values with secrets replaced by the mask if present."""
    c = cfg.load_config()
    view = {}
    for _, fields in SECTIONS:
        for f in fields:
            k = f["key"]
            v = c.get(k, "")
            if k in SECRET_KEYS and v:
                view[k] = MASK
            else:
                view[k] = v if v != "" else f.get("default", "")
    return view


@app.route("/")
def index():
    p = Path(__file__).parent / "templates" / "dashboard.html"
    return p.read_text(encoding="utf-8"), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/config")
def config_page():
    return render_template("config.html", sections=SECTIONS, values=_view_config(), mask=MASK)


@app.route("/save", methods=["POST"])
def save():
    existing = cfg.load_config()
    updates = {}
    for _, fields in SECTIONS:
        for f in fields:
            k = f["key"]
            if k not in request.form:
                continue
            val = request.form.get(k, "").strip()
            if k in SECRET_KEYS:
                # keep existing secret if the field is blank or still the mask
                if val == "" or set(val) <= set("•"):
                    continue
            updates[k] = val
    existing.update(updates)
    cfg.save_config(existing)
    return jsonify({"ok": True, "saved": sorted(updates.keys())})


@app.route("/test/kalshi", methods=["POST"])
def test_kalshi():
    """Verify the ACTIVE account: balance + the live front market (prices are prod)."""
    try:
        from btc_kalshi import kalshi
        _, _, _, _, base, acct = cfg.get_credentials()
        bal = kalshi.get_balance()
        mkt = kalshi.get_front_market()
        return jsonify({
            "ok": bal is not None,
            "active_account": acct,
            "endpoint": base,
            "balance_usd": bal,
            "front_market": ({"ticker": mkt.get("ticker"), "strike": mkt.get("strike"),
                              "mins_remaining": mkt.get("mins_remaining"),
                              "yes_ask": mkt.get("yes_ask"), "no_ask": mkt.get("no_ask")}
                             if mkt else None),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/state")
def api_state():
    """One light snapshot for the dashboard (account, balance, positions, contract,
    spot, technicals, derivatives, latest decision). Network calls are best-effort."""
    out = {"ts": __import__("time").time()}
    try:
        _, _, _, _, base, acct = cfg.get_credentials()
        out["account"] = acct
        out["endpoint"] = base
        out["mode"] = "DEMO" if acct == 2 else "REAL"
    except Exception:
        out["account"] = None
    try:
        out["balance"] = kalshi.get_balance()
    except Exception:
        out["balance"] = None
    try:
        out["positions"] = kalshi.get_positions()
    except Exception:
        out["positions"] = []
    try:
        m = contract_context.get_contract()
        if m:
            m["implied_prob"] = contract_context.implied_prob(m.get("yes_ask"), m.get("yes_bid"))
        out["contract"] = m
    except Exception:
        out["contract"] = None
    try:
        out["spot"] = crypto_data.get_spot()
        out["features"] = crypto_data.compute_features(crypto_data.get_klines("1m", 60))
    except Exception:
        out["features"] = {}
    try:
        out["funding"] = crypto_fundamentals.get_funding()
        out["open_interest"] = crypto_fundamentals.get_open_interest()
        out["long_short"] = crypto_fundamentals.get_long_short_ratio()
    except Exception:
        pass
    try:
        out["decisions"] = logstore.read_decisions(12)
    except Exception:
        out["decisions"] = []
    bv = cfg.load_config().get("buying_enabled", False)
    out["buying"] = bv is True or str(bv).lower() in ("1", "true", "yes")
    out["running"] = procman.is_running()
    return jsonify(out)


@app.route("/api/system", methods=["GET", "POST"])
def api_system():
    """Run / stop the agent loop (the 'Run System' button)."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        if body.get("run"):
            return jsonify(procman.start_runner())
        return jsonify(procman.stop_runner())
    return jsonify(procman.status())


@app.route("/api/buying", methods=["POST"])
def api_buying():
    """Turn buying on/off (the 'Enable Buying' button). Merges, never clobbers keys."""
    body = request.get_json(silent=True) or {}
    on = bool(body.get("on"))
    cfg.update_config(buying_enabled=on)
    return jsonify({"ok": True, "buying": on})


@app.route("/api/price")
def api_price():
    """Recent 1m candles for the live price chart + the contract chart strike line."""
    try:
        candles = crypto_data.get_klines("1m", 120)
    except Exception:
        candles = []
    spot = None
    try:
        spot = crypto_data.get_spot()
    except Exception:
        pass
    return jsonify({"spot": spot, "candles": candles})


if __name__ == "__main__":
    port = int(os.getenv("CONFIG_PORT", "5057"))
    print(f"\n  BTCAgents config page → http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
