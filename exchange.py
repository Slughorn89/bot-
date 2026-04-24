from typing import Optional

import ccxt
import pandas as pd

from logger import get_logger

log = get_logger("Exchange")


class ExchangeClient:
    def __init__(self, exchange_id: str, api_key: str, api_secret: str, dry_run: bool = True):
        self.dry_run = dry_run
        exchange_class = getattr(ccxt, exchange_id, None)
        if exchange_class is None:
            raise ValueError(f"Exchange '{exchange_id}' not supported by ccxt")

        self.client = exchange_class({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })

        mode = "DRY RUN (paper trading)" if dry_run else "LIVE trading"
        log.info(f"Connected to {exchange_id} [{mode}]")

    def fetch_ohlcv(self, pair: str, timeframe: str = "1h", limit: int = 200) -> pd.DataFrame:
        raw = self.client.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def fetch_ticker(self, pair: str) -> dict:
        return self.client.fetch_ticker(pair)

    def fetch_balance(self) -> dict:
        if self.dry_run:
            return {"USDT": {"free": 1000.0, "used": 0.0, "total": 1000.0}}
        return self.client.fetch_balance()

    def get_free_balance(self, currency: str = "USDT") -> float:
        balance = self.fetch_balance()
        return balance.get(currency, {}).get("free", 0.0)

    def place_market_order(self, pair: str, side: str, amount: float) -> Optional[dict]:
        if self.dry_run:
            ticker = self.fetch_ticker(pair)
            price = ticker["last"]
            log.info(f"[DRY RUN] {side.upper()} {amount:.6f} {pair} @ {price:.4f}")
            return {"id": "dry-run", "price": price, "amount": amount, "side": side, "status": "closed"}

        try:
            order = self.client.create_market_order(pair, side, amount)
            log.info(f"Order placed: {side.upper()} {amount:.6f} {pair} | ID: {order['id']}")
            return order
        except ccxt.BaseError as e:
            log.error(f"Order failed: {e}")
            return None
