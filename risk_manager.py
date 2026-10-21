from dataclasses import dataclass
from typing import Dict, Optional

from logger import get_logger

log = get_logger("RiskManager")


@dataclass
class Position:
    pair: str
    side: str          # "long" or "short"
    entry_price: float
    amount: float
    stop_loss: float
    take_profit: Optional[float]
    cost: float = 0.0

    def current_pnl(self, current_price: float) -> float:
        if self.side == "long":
            return (current_price - self.entry_price) / self.entry_price
        return (self.entry_price - current_price) / self.entry_price


class RiskManager:
    def __init__(self, max_position_size: float, stop_loss_pct: float,
                 take_profit_pct: float, max_open_trades: int):
        self.max_position_size = max_position_size
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_open_trades = max_open_trades
        self.positions: Dict[str, Position] = {}

    def can_open_trade(self, pair: str) -> bool:
        if pair in self.positions:
            log.warning(f"Position already open for {pair}")
            return False
        if len(self.positions) >= self.max_open_trades:
            log.warning(f"Max open trades reached ({self.max_open_trades})")
            return False
        return True

    def calculate_order_size(self, balance: float, price: float) -> float:
        max_cost = balance * self.max_position_size
        return max_cost / price

    def calculate_stop_loss(self, entry_price: float, side: str = "long") -> float:
        if side == "long":
            return entry_price * (1 - self.stop_loss_pct)
        return entry_price * (1 + self.stop_loss_pct)

    def calculate_take_profit(self, entry_price: float, side: str = "long") -> float:
        if side == "long":
            return entry_price * (1 + self.take_profit_pct)
        return entry_price * (1 - self.take_profit_pct)

    @staticmethod
    def size_by_risk(equity: float, price: float, stop_distance: float,
                     risk: float, max_alloc: float) -> float:
        """Units such that hitting the stop loses `risk` of equity, capped at max_alloc."""
        if stop_distance <= 0:
            return 0.0
        return min(equity * risk / stop_distance, equity * max_alloc / price)

    def open_position(self, pair: str, side: str, entry_price: float,
                      amount: float, stop_loss: Optional[float] = None,
                      take_profit: Optional[float] = None,
                      custom_exits: bool = False) -> Optional[Position]:
        if not self.can_open_trade(pair):
            return None

        if not custom_exits:
            stop_loss = self.calculate_stop_loss(entry_price, side)
            take_profit = self.calculate_take_profit(entry_price, side)

        position = Position(
            pair=pair,
            side=side,
            entry_price=entry_price,
            amount=amount,
            stop_loss=stop_loss,
            take_profit=take_profit,
            cost=entry_price * amount,
        )
        self.positions[pair] = position
        log.info(
            f"Opened {side.upper()} position: {pair} | Entry: {entry_price:.4f} | "
            f"Amount: {amount:.6f} | SL: {stop_loss:.4f} | "
            f"TP: {'none' if take_profit is None else format(take_profit, '.4f')}"
        )
        return position

    def close_position(self, pair: str) -> Optional[Position]:
        pos = self.positions.pop(pair, None)
        if pos:
            log.info(f"Closed position: {pair}")
        return pos

    def check_exits(self, pair: str, current_price: float) -> Optional[str]:
        pos = self.positions.get(pair)
        if not pos:
            return None

        if pos.side == "long":
            if current_price <= pos.stop_loss:
                pct = pos.current_pnl(current_price) * 100
                log.warning(f"Stop loss triggered for {pair}: {pct:.2f}%")
                return "stop_loss"
            if pos.take_profit is not None and current_price >= pos.take_profit:
                pct = pos.current_pnl(current_price) * 100
                log.info(f"Take profit triggered for {pair}: +{pct:.2f}%")
                return "take_profit"
        return None
