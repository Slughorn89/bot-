import time
from datetime import datetime, timezone
from typing import Optional

from config import Config
from exchange import ExchangeClient
from logger import get_logger
from risk_manager import RiskManager
from strategy import Signal, get_strategy
from trade_log import trade_log
from whales import WhaleWatcher

log = get_logger("TradingBot")

TF_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900,
              "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


class TradingBot:
    def __init__(self, config: Config = None):
        cfg = config or Config()
        self.cfg = cfg

        self.pair = cfg.TRADING_PAIR
        self.timeframe = cfg.TIMEFRAME
        self.dry_run = cfg.DRY_RUN

        self.exchange = ExchangeClient(
            exchange_id=cfg.EXCHANGE,
            api_key=cfg.API_KEY,
            api_secret=cfg.API_SECRET,
            dry_run=cfg.DRY_RUN,
        )

        self.strategy = get_strategy(cfg.STRATEGY, cfg.BEST_PARAMS_FILE)

        self.risk = RiskManager(
            max_position_size=cfg.MAX_POSITION_SIZE,
            stop_loss_pct=cfg.STOP_LOSS_PCT,
            take_profit_pct=cfg.TAKE_PROFIT_PCT,
            max_open_trades=cfg.MAX_OPEN_TRADES,
        )

        self.whales: Optional[WhaleWatcher] = None
        if cfg.WHALE_MODE != "off":
            self.whales = WhaleWatcher(
                self.exchange.client, self.pair,
                min_usd=cfg.WHALE_MIN_USD, flow_min_usd=cfg.WHALE_FLOW_MIN_USD,
                poll_s=cfg.WHALE_POLL_SECONDS, addresses=cfg.WHALE_ADDRESSES,
                on_event=trade_log.add_whale_event,
            )

        self.running = False
        self._last_candle = None  # timestamp of the last closed candle already evaluated
        trade_log.update_status(
            started_at=datetime.now(timezone.utc).isoformat(),
            strategy=cfg.STRATEGY,
            pair=self.pair,
            timeframe=self.timeframe,
            dry_run=self.dry_run,
            whale_mode=cfg.WHALE_MODE,
        )

        log.info(
            f"Bot initialized | Pair: {self.pair} | TF: {self.timeframe} | "
            f"Strategy: {cfg.STRATEGY} | DryRun: {self.dry_run} | Whales: {cfg.WHALE_MODE}"
        )

    # ------------------------------------------------------------------ tick
    def tick(self):
        try:
            current_price = self.exchange.fetch_ticker(self.pair)["last"]

            # Stops/targets are checked on every poll (every few seconds-minutes)...
            exit_reason = self.risk.check_exits(self.pair, current_price)
            if exit_reason:
                self._close_trade(current_price, exit_reason)
                self._sync_status(current_price)
                return

            # ...but the strategy only evaluates each CLOSED candle once, exactly
            # as it was backtested (signal at close, execution right after).
            df = self.exchange.fetch_ohlcv(self.pair, self.timeframe, limit=300, closed_only=True)
            candle_ts = df.index[-1]
            if candle_ts != self._last_candle:
                self._last_candle = candle_ts
                self._evaluate(df, current_price)

            self._sync_status(current_price)

        except Exception as e:
            log.error(f"Tick error: {e}", exc_info=True)

    def _evaluate(self, df, price: float):
        result = self.strategy.analyze(df)
        log.info(f"Candle {df.index[-1]} | Signal: {result.signal.value} | {result.reason}")
        trade_log.add_signal(result.signal.value, price, result.reason)

        if result.signal == Signal.BUY and self.pair not in self.risk.positions:
            if self._whales_block_entry():
                return
            self._open_long(price, result)
        elif result.signal == Signal.SELL and self.pair in self.risk.positions:
            self._close_trade(price, "strategy_signal")

    def _whales_block_entry(self) -> bool:
        if not self.whales or self.cfg.WHALE_MODE != "filter":
            return False
        snap = self.whales.snapshot()
        if snap.updated_at and snap.score <= -self.cfg.WHALE_BLOCK_SCORE:
            log.warning(f"BUY blocked by whale filter (score {snap.score:+.2f}, "
                        f"net flow ${snap.flow_usd:,.0f})")
            trade_log.add_signal("BLOCKED", 0.0, f"whale score {snap.score:+.2f}")
            return True
        return False

    # ----------------------------------------------------------------- status
    def _sync_status(self, current_price: float):
        pos = self.risk.positions.get(self.pair)
        pos_dict = None
        if pos:
            pos_dict = {
                "side": pos.side,
                "entry_price": pos.entry_price,
                "amount": pos.amount,
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
                "current_pnl_pct": pos.current_pnl(current_price) * 100,
            }
        whale = None
        if self.whales:
            s = self.whales.snapshot()
            whale = {"score": s.score, "flow_usd": s.flow_usd, "book_imbalance": s.book_imbalance,
                     "top_trader_shift": s.top_trader_shift, "hl_net_usd_1h": s.hl_net_usd_1h,
                     "hl_tracked": s.hl_tracked, "sources_ok": s.sources_ok,
                     "updated_at": s.updated_at}
        trade_log.update_status(
            current_position=pos_dict,
            equity=self.exchange.get_free_balance("USDT"),
            last_price=current_price,
            whale=whale,
        )

    # ----------------------------------------------------------------- orders
    def _open_long(self, price: float, result):
        balance = self.exchange.get_free_balance("USDT")
        custom = result.stop_distance is not None
        if custom:
            amount = self.risk.size_by_risk(balance, price, result.stop_distance,
                                            self.cfg.RISK_PER_TRADE, self.cfg.MAX_ALLOC)
        else:
            amount = self.risk.calculate_order_size(balance, price)
        if amount <= 0:
            log.warning("Insufficient balance to open trade")
            return

        order = self.exchange.place_market_order(self.pair, "buy", amount)
        if order:
            fill = order.get("price", price)
            if custom:
                tp = fill + result.target_distance if result.target_distance else None
                self.risk.open_position(self.pair, "long", fill, amount,
                                        stop_loss=fill - result.stop_distance,
                                        take_profit=tp, custom_exits=True)
            else:
                self.risk.open_position(self.pair, "long", fill, amount)

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
            trade_log.add_trade(
                side=pos.side,
                entry_price=pos.entry_price,
                exit_price=price,
                amount=pos.amount,
                pnl_usdt=pnl_usdt,
                pnl_pct=pnl_pct,
                reason=reason,
            )
            self.risk.close_position(self.pair)

    # -------------------------------------------------------------------- run
    def run(self, interval_seconds: Optional[int] = None):
        tf = TF_SECONDS.get(self.timeframe, 3600)
        interval = interval_seconds or min(self.cfg.POLL_SECONDS, tf)

        self.running = True
        if self.whales:
            self.whales.start()
        log.info(f"Bot started. Polling every {interval}s (strategy acts once per closed {self.timeframe} candle).")

        try:
            while self.running:
                self.tick()
                time.sleep(interval)
        except KeyboardInterrupt:
            log.info("Bot stopped by user.")
        finally:
            self.running = False
            if self.whales:
                self.whales.stop()

    def stop(self):
        self.running = False
        log.info("Stop signal sent.")
