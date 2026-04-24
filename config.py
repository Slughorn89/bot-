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
