import json
import os
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional


class TradeLog:
    """Thread-safe in-memory log of signals and trades, persisted to JSON."""

    def __init__(self, path: str = "trade_log.json", max_signals: int = 500,
                 max_trades: int = 200):
        self.path = path
        self._lock = threading.Lock()
        self._signals: deque = deque(maxlen=max_signals)
        self._trades: deque = deque(maxlen=max_trades)
        self._status: dict = {
            "started_at": None,
            "last_tick": None,
            "current_position": None,
            "equity": 0.0,
            "strategy": None,
            "pair": None,
            "timeframe": None,
            "dry_run": True,
        }
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            self._signals.extend(data.get("signals", []))
            self._trades.extend(data.get("trades", []))
            self._status.update(data.get("status", {}))
        except Exception:
            pass

    def _save(self):
        with open(self.path, "w") as f:
            json.dump({
                "signals": list(self._signals),
                "trades": list(self._trades),
                "status": self._status,
            }, f, indent=2)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def add_signal(self, signal: str, price: float, reason: str):
        with self._lock:
            self._signals.append({
                "timestamp": self._now(),
                "signal": signal,
                "price": float(price),
                "reason": reason,
            })
            self._save()

    def add_trade(self, side: str, entry_price: float, exit_price: Optional[float],
                  amount: float, pnl_usdt: float, pnl_pct: float, reason: str):
        with self._lock:
            self._trades.append({
                "timestamp": self._now(),
                "side": side,
                "entry_price": float(entry_price),
                "exit_price": float(exit_price) if exit_price is not None else None,
                "amount": float(amount),
                "pnl_usdt": float(pnl_usdt),
                "pnl_pct": float(pnl_pct),
                "reason": reason,
            })
            self._save()

    def update_status(self, **kwargs):
        with self._lock:
            self._status.update(kwargs)
            self._status["last_tick"] = self._now()
            self._save()

    def get_state(self) -> dict:
        with self._lock:
            return {
                "signals": list(self._signals),
                "trades": list(self._trades),
                "status": dict(self._status),
            }


trade_log = TradeLog()
