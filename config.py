import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        self.EXCHANGE = os.getenv("EXCHANGE", "binance")
        self.API_KEY = os.getenv("API_KEY", "")
        self.API_SECRET = os.getenv("API_SECRET", "")
        self.TRADING_PAIR = os.getenv("TRADING_PAIR", "BTC/USDT")
        self.TIMEFRAME = os.getenv("TIMEFRAME", "1h")
        self.DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
        self.MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "0.1"))
        self.STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.02"))
        self.TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.04"))
        self.MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "3"))
        self.STRATEGY = os.getenv("STRATEGY", "MA_CROSSOVER")
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

        # OPTIMIZED strategy (parameters produced by optimize.py)
        self.BEST_PARAMS_FILE = os.getenv("BEST_PARAMS_FILE", "best_params.json")
        self.RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.02"))
        self.MAX_ALLOC = float(os.getenv("MAX_ALLOC", "0.5"))
        self.POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))

        # Whale monitoring: off | alert (log only) | filter (block BUY when whales sell)
        self.WHALE_MODE = os.getenv("WHALE_MODE", "filter").lower()
        self.WHALE_MIN_USD = float(os.getenv("WHALE_MIN_USD", "1000000"))
        self.WHALE_FLOW_MIN_USD = float(os.getenv("WHALE_FLOW_MIN_USD", "100000"))
        self.WHALE_POLL_SECONDS = int(os.getenv("WHALE_POLL_SECONDS", "30"))
        self.WHALE_BLOCK_SCORE = float(os.getenv("WHALE_BLOCK_SCORE", "0.35"))
        self.WHALE_ADDRESSES = [a.strip() for a in os.getenv("WHALE_ADDRESSES", "").split(",") if a.strip()]
