#!/usr/bin/env python3
"""
Trading Bot - Entry Point
Usage:
    python main.py
    DRY_RUN=true STRATEGY=RSI python main.py
    python main.py --strategy RSI --pair ETH/USDT --timeframe 15m
"""

import argparse
import os
import sys

from config import Config
from logger import get_logger

log = get_logger("Main")


def parse_args():
    parser = argparse.ArgumentParser(description="Automated Trading Bot")
    parser.add_argument("--pair", help="Trading pair (e.g. BTC/USDT)")
    parser.add_argument("--timeframe", help="Candle timeframe (e.g. 1h)")
    parser.add_argument("--strategy", choices=["MA_CROSSOVER", "RSI", "MACD"],
                        help="Trading strategy")
    parser.add_argument("--dry-run", action="store_true",
                        help="Paper trading mode (no real orders)")
    parser.add_argument("--live", action="store_true",
                        help="Enable live trading (real money!)")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.pair:
        os.environ["TRADING_PAIR"] = args.pair
    if args.timeframe:
        os.environ["TIMEFRAME"] = args.timeframe
    if args.strategy:
        os.environ["STRATEGY"] = args.strategy
    if args.live:
        os.environ["DRY_RUN"] = "false"
        log.warning("LIVE TRADING MODE ENABLED - Real money at risk!")
    elif args.dry_run:
        os.environ["DRY_RUN"] = "true"

    cfg = Config()

    if not cfg.DRY_RUN and (not cfg.API_KEY or not cfg.API_SECRET):
        log.error("API_KEY and API_SECRET must be set for live trading.")
        sys.exit(1)

    log.info("=" * 60)
    log.info("  TRADING BOT")
    log.info("=" * 60)
    log.info(f"  Exchange : {cfg.EXCHANGE}")
    log.info(f"  Pair     : {cfg.TRADING_PAIR}")
    log.info(f"  Timeframe: {cfg.TIMEFRAME}")
    log.info(f"  Strategy : {cfg.STRATEGY}")
    log.info(f"  Mode     : {'DRY RUN (paper)' if cfg.DRY_RUN else 'LIVE'}")
    log.info(f"  SL/TP    : {cfg.STOP_LOSS_PCT*100:.1f}% / {cfg.TAKE_PROFIT_PCT*100:.1f}%")
    log.info("=" * 60)

    from bot import TradingBot
    bot = TradingBot(cfg)
    bot.run()


if __name__ == "__main__":
    main()
