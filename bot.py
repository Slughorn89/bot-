import time
from typing import Optional

from config import Config
from exchange import ExchangeClient
from logger import get_logger
from risk_manager import RiskManager
from strategy import Signal, get_strategy

log = get_logger("TradingBot")


class TradingBot:
    def __init__(self, config: Config = None):
        cfg = config or Config()

        self.pair = cfg.TRADING_PAIR
        self.timeframe = cfg.TIMEFRAME
        self.dry_run = cfg.DRY_RUN

        self.exchange = ExchangeClient(
            exchange_id=cfg.EXCHANGE,
            api_key=cfg.API_KEY,
            api_secret=cfg.API_SECRET,
            dry_run=cfg.DRY_RUN,
        )

        self.strategy = get_strategy(cfg.STRATEGY)

        self.risk = RiskManager(
            max_position_size=cfg.MAX_POSITION_SIZE,
            stop_loss_pct=cfg.STOP_LOSS_PCT,
            take_profit_pct=cfg.TAKE_PROFIT_PCT,
            max_open_trades=cfg.MAX_OPEN_TRADES,
        )

        self.running = False
        log.info(
            f"Bot initialized | Pair: {self.pair} | TF: {self.timeframe} | "
            f"Strategy: {cfg.STRATEGY} | DryRun: {self.dry_run}"
        )

    def tick(self):
        try:
            df = self.exchange.fetch_ohlcv(self.pair, self.timeframe, limit=200)
            ticker = self.exchange.fetch_ticker(self.pair)
            current_price = ticker["last"]

            log.debug(f"{self.pair} price: {current_price:.4f}")

            exit_reason = self.risk.check_exits(self.pair, current_price)
            if exit_reason:
                self._close_trade(current_price, exit_reason)
                return

            result = self.strategy.analyze(df)
            log.info(f"Signal: {result.signal.value} | {result.reason}")

            if result.signal == Signal.BUY and self.pair not in self.risk.positions:
                self._open_long(current_price)
            elif result.signal == Signal.SELL and self.pair in self.risk.positions:
                self._close_trade(current_price, "strategy_signal")

        except Exception as e:
            log.error(f"Tick error: {e}", exc_info=True)

    def _open_long(self, price: float):
        balance = self.exchange.get_free_balance("USDT")
        amount = self.risk.calculate_order_size(balance, price)
        if amount <= 0:
            log.warning("Insufficient balance to open trade")
            return

        order = self.exchange.place_market_order(self.pair, "buy", amount)
        if order:
            filled_price = order.get("price", price)
            self.risk.open_position(self.pair, "long", filled_price, amount)

    def _close_trade(self, price: float, reason: str):
        pos = self.risk.positions.get(self.pair)
        if not pos:
            return

        order = self.exchange.place_market_order(self.pair, "sell", pos.amount)
        if order:
            pnl_pct = pos.current_pnl(price) * 100
            pnl_usdt = (price - pos.entry_price) * pos.amount
            log.info(
                f"Trade closed [{reason}] | Entry: {pos.entry_price:.4f} | "
                f"Exit: {price:.4f} | PnL: {pnl_pct:+.2f}% ({pnl_usdt:+.4f} USDT)"
            )
            self.risk.close_position(self.pair)

    def run(self, interval_seconds: Optional[int] = None):
        tf_seconds = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900,
            "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400,
        }
        interval = interval_seconds or tf_seconds.get(self.timeframe, 3600)

        self.running = True
        log.info(f"Bot started. Polling every {interval}s.")

        try:
            while self.running:
                self.tick()
                log.debug(f"Sleeping {interval}s until next tick...")
                time.sleep(interval)
        except KeyboardInterrupt:
            log.info("Bot stopped by user.")
        finally:
            self.running = False

    def stop(self):
        self.running = False
        log.info("Stop signal sent.")
