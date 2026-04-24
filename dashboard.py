#!/usr/bin/env python3
"""
Live web dashboard for the trading bot.
Runs the bot in a background thread and serves a chart UI on http://localhost:5000.

Usage:
    python dashboard.py
    python dashboard.py --port 8080 --no-bot   # only API + chart, no bot
"""

import argparse
import os
import threading
from typing import Optional

from flask import Flask, jsonify, request

from config import Config
from exchange import ExchangeClient
from logger import get_logger
from trade_log import trade_log

log = get_logger("Dashboard")

app = Flask(__name__, static_folder="static", static_url_path="/static")

_bot_thread: Optional[threading.Thread] = None
_shared_exchange: Optional[ExchangeClient] = None


def _get_exchange() -> ExchangeClient:
    global _shared_exchange
    if _shared_exchange is None:
        cfg = Config()
        _shared_exchange = ExchangeClient(
            exchange_id=cfg.EXCHANGE,
            api_key=cfg.API_KEY,
            api_secret=cfg.API_SECRET,
            dry_run=True,
        )
    return _shared_exchange


def start_bot_thread():
    global _bot_thread
    if _bot_thread is not None and _bot_thread.is_alive():
        return
    from bot import TradingBot
    cfg = Config()
    bot = TradingBot(cfg)
    _bot_thread = threading.Thread(target=bot.run, daemon=True, name="TradingBot")
    _bot_thread.start()
    log.info("Bot thread started in background")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    here = os.path.dirname(__file__)
    return open(os.path.join(here, "static", "dashboard.html"), encoding="utf-8").read()


@app.route("/api/candles")
def api_candles():
    pair = request.args.get("pair", Config.TRADING_PAIR)
    timeframe = request.args.get("timeframe", Config.TIMEFRAME)
    limit = int(request.args.get("limit", 200))

    try:
        df = _get_exchange().fetch_ohlcv(pair, timeframe, limit)
    except Exception as e:
        log.error(f"Failed to fetch candles: {e}")
        return jsonify({"error": str(e)}), 500

    candles = [
        {
            "time": int(ts.timestamp()),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
        for ts, row in df.iterrows()
    ]
    return jsonify({"pair": pair, "timeframe": timeframe, "candles": candles})


@app.route("/api/state")
def api_state():
    return jsonify(trade_log.get_state())


@app.route("/api/health")
def api_health():
    bot_alive = _bot_thread is not None and _bot_thread.is_alive()
    return jsonify({"status": "ok", "bot_running": bot_alive})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Trading bot dashboard")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument("--no-bot", action="store_true",
                        help="Run only API + UI, do not start the trading bot")
    args = parser.parse_args()

    if not args.no_bot:
        start_bot_thread()
    else:
        log.info("Bot disabled (--no-bot). Serving chart only.")

    log.info(f"Dashboard: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
