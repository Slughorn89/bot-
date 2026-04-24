import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Exchange
    EXCHANGE = os.getenv("EXCHANGE", "binance")
    API_KEY = os.getenv("API_KEY", "")
    API_SECRET = os.getenv("API_SECRET", "")

    # Trading
    TRADING_PAIR = os.getenv("TRADING_PAIR", "BTC/USDT")
    TIMEFRAME = os.getenv("TIMEFRAME", "1h")
    DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

    # Risk Management
    MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "0.1"))
    STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.02"))
    TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.04"))
    MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "3"))

    # Strategy
    STRATEGY = os.getenv("STRATEGY", "MA_CROSSOVER")

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
