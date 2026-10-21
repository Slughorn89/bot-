"""Whale / large-player monitoring from PUBLIC data sources only.

Sources
  1. Exchange tape  - single trades >= WHALE_MIN_USD are alerts; trades >= WHALE_FLOW_MIN_USD
                      feed a rolling net-flow (aggressive buys - aggressive sells).
  2. Order book     - bid/ask depth imbalance within 1% of mid + big resting walls
                      (walls can be spoofed, so they carry a small weight).
  3. Binance Futures top-trader long/short position ratio (shift vs its own recent history).
  4. Hyperliquid    - perp positions of the biggest leaderboard accounts (+ your own
                      WHALE_ADDRESSES). New/changed/closed positions >= WHALE_MIN_USD are alerts.

The combined score is in [-1, 1] (+ = whales net buying/long). It is a heuristic and
CANNOT be backtested (no historical snapshots), so it is used as a filter/alert, not
as a proven edge. You cannot see individual Binance accounts - only public data.
"""
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import requests

from logger import get_logger

log = get_logger("Whales")

HL_INFO = "https://api.hyperliquid.xyz/info"
HL_LEADERBOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
BINANCE_FAPI = "https://fapi.binance.com"


@dataclass
class WhaleSnapshot:
    score: float = 0.0
    flow_usd: float = 0.0          # net aggressive whale flow over the window
    book_imbalance: float = 0.0    # (bids-asks)/(bids+asks) within 1% of mid
    top_trader_shift: float = 0.0  # z-score-like shift of top-trader long ratio, [-1,1]
    hl_net_usd_1h: float = 0.0     # net signed Hyperliquid position change, last hour
    hl_tracked: int = 0
    updated_at: float = 0.0
    sources_ok: Dict[str, bool] = field(default_factory=dict)


def parse_positions(state: dict) -> Dict[str, float]:
    """Hyperliquid clearinghouseState -> {coin: signed notional USD}."""
    out = {}
    for ap in state.get("assetPositions", []):
        p = ap.get("position", {})
        try:
            out[p["coin"]] = math.copysign(abs(float(p["positionValue"])), float(p["szi"]))
        except (KeyError, ValueError):
            continue
    return out


def diff_positions(addr: str, old: Dict[str, float], new: Dict[str, float],
                   min_usd: float) -> List[dict]:
    events = []
    for coin in set(old) | set(new):
        o, n = old.get(coin, 0.0), new.get(coin, 0.0)
        delta = n - o
        if abs(delta) < min_usd and abs(n) < min_usd:
            continue
        if o == 0 and abs(n) >= min_usd:
            kind = "OPENED_LONG" if n > 0 else "OPENED_SHORT"
        elif n == 0 and abs(o) >= min_usd:
            kind = "CLOSED"
        elif o * n < 0:
            kind = "FLIPPED_" + ("LONG" if n > 0 else "SHORT")
        elif abs(delta) >= min_usd:
            kind = "INCREASED" if abs(n) > abs(o) else "REDUCED"
        else:
            continue
        events.append({"source": "hyperliquid", "kind": kind, "coin": coin, "address": addr,
                       "usd": n, "delta_usd": delta})
    return events


def score_from(flow, book, shift, hl, min_usd) -> float:
    flow_s = math.tanh(flow / (5 * min_usd))
    hl_s = math.tanh(hl / (10 * min_usd))
    s = 0.4 * flow_s + 0.3 * hl_s + 0.2 * shift + 0.1 * book
    return max(-1.0, min(1.0, s))


class WhaleWatcher:
    def __init__(self, ccxt_client, pair: str, min_usd: float = 1_000_000,
                 flow_min_usd: float = 100_000, window_s: int = 3600,
                 poll_s: int = 30, addresses: Optional[List[str]] = None,
                 hl_top_n: int = 30, on_event: Optional[Callable[[dict], None]] = None):
        self.ex, self.pair = ccxt_client, pair
        self.base = pair.split("/")[0]
        self.min_usd, self.flow_min, self.window = min_usd, flow_min_usd, window_s
        self.poll_s, self.hl_top_n = poll_s, hl_top_n
        self.manual = [a.lower() for a in (addresses or []) if a]
        self.on_event = on_event or (lambda e: None)
        self._trades: deque = deque()         # (ts, signed_usd)
        self._seen_ids: deque = deque(maxlen=5000)
        self._last_trade_ts: Optional[int] = None
        self._hl_pos: Dict[str, Dict[str, float]] = {}
        self._hl_deltas: deque = deque()      # (ts, signed delta on base coin)
        self._hl_addrs: List[str] = []
        self._hl_addrs_ts = 0.0
        self._snap = WhaleSnapshot()
        self._book = 0.0
        self._shift = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.session = requests.Session()

    # ---------------------------------------------------------------- sources
    def _emit(self, ev: dict):
        ev["ts"] = time.time()
        log.warning(f"WHALE {ev['source']} {ev['kind']} {ev.get('coin', self.base)} "
                    f"${abs(ev.get('usd', 0)):,.0f}")
        try:
            self.on_event(ev)
        except Exception as e:  # never let a UI callback kill the watcher
            log.error(f"on_event failed: {e}")

    def ingest_trades(self, trades: List[dict]):
        """trades: ccxt-style dicts (id, timestamp ms, side, cost, price, amount)."""
        for t in trades:
            tid = t.get("id")
            if tid is not None:
                if tid in self._seen_ids:
                    continue
                self._seen_ids.append(tid)
            cost = t.get("cost") or (t["price"] * t["amount"])
            sign = 1.0 if t.get("side") == "buy" else -1.0
            ts = t["timestamp"] / 1000
            if cost >= self.flow_min:
                self._trades.append((ts, sign * cost))
            if cost >= self.min_usd:
                self._emit({"source": "tape", "kind": "BIG_BUY" if sign > 0 else "BIG_SELL",
                            "usd": sign * cost, "price": t.get("price")})
            self._last_trade_ts = max(self._last_trade_ts or 0, t["timestamp"])
        cutoff = time.time() - self.window
        while self._trades and self._trades[0][0] < cutoff:
            self._trades.popleft()

    def _scan_tape(self):
        since = (self._last_trade_ts + 1) if self._last_trade_ts else int((time.time() - 600) * 1000)
        self.ingest_trades(self.ex.fetch_trades(self.pair, since=since, limit=1000))

    def _scan_book(self):
        ob = self.ex.fetch_order_book(self.pair, limit=100)
        mid = (ob["bids"][0][0] + ob["asks"][0][0]) / 2
        bids = [(p, a) for p, a, *_ in ob["bids"] if p >= mid * 0.99]
        asks = [(p, a) for p, a, *_ in ob["asks"] if p <= mid * 1.01]
        b, a = sum(p * q for p, q in bids), sum(p * q for p, q in asks)
        self._book = (b - a) / (b + a) if (b + a) else 0.0
        for side, lv in (("BID_WALL", bids), ("ASK_WALL", asks)):
            for p, q in lv:
                if p * q >= self.min_usd:
                    log.info(f"{side} ${p * q:,.0f} @ {p:,.2f} (may be spoofed)")

    def _scan_top_traders(self):
        sym = self.pair.replace("/", "").replace(":USDT", "")
        r = self.session.get(f"{BINANCE_FAPI}/futures/data/topLongShortPositionRatio",
                             params={"symbol": sym, "period": "1h", "limit": 30}, timeout=15)
        r.raise_for_status()
        vals = [float(x["longAccount"]) for x in r.json()]
        if len(vals) >= 5:
            mean = sum(vals[:-1]) / (len(vals) - 1)
            sd = (sum((v - mean) ** 2 for v in vals[:-1]) / (len(vals) - 1)) ** 0.5 or 1e-9
            self._shift = max(-1.0, min(1.0, (vals[-1] - mean) / sd / 2))

    def _refresh_hl_addresses(self):
        if time.time() - self._hl_addrs_ts < 3600 and self._hl_addrs:
            return
        addrs = list(self.manual)
        try:
            rows = self.session.get(HL_LEADERBOARD, timeout=30).json().get("leaderboardRows", [])
            rows = [r for r in rows if float(r.get("accountValue", 0)) >= self.min_usd]
            rows.sort(key=lambda r: -float(r["accountValue"]))
            addrs += [r["ethAddress"].lower() for r in rows[: self.hl_top_n]]
        except Exception as e:
            log.warning(f"Hyperliquid leaderboard unavailable: {e}")
        self._hl_addrs, self._hl_addrs_ts = list(dict.fromkeys(addrs)), time.time()

    def _scan_hyperliquid(self):
        self._refresh_hl_addresses()
        for addr in self._hl_addrs:
            r = self.session.post(HL_INFO, json={"type": "clearinghouseState", "user": addr}, timeout=15)
            r.raise_for_status()
            new = parse_positions(r.json())
            if addr in self._hl_pos:  # first sight = baseline, no events
                for ev in diff_positions(addr, self._hl_pos[addr], new, self.min_usd):
                    self._emit(ev)
                    if ev["coin"] == self.base:
                        self._hl_deltas.append((time.time(), ev["delta_usd"]))
            self._hl_pos[addr] = new
        cutoff = time.time() - self.window
        while self._hl_deltas and self._hl_deltas[0][0] < cutoff:
            self._hl_deltas.popleft()

    # ---------------------------------------------------------------- loop
    def poll_once(self):
        ok = {}
        for name, fn in (("tape", self._scan_tape), ("book", self._scan_book),
                         ("top_traders", self._scan_top_traders),
                         ("hyperliquid", self._scan_hyperliquid)):
            try:
                fn()
                ok[name] = True
            except Exception as e:
                ok[name] = False
                log.debug(f"{name} scan failed: {e}")
        flow = sum(v for _, v in self._trades)
        hl = sum(v for _, v in self._hl_deltas)
        snap = WhaleSnapshot(score_from(flow, self._book, self._shift, hl, self.min_usd),
                             flow, self._book, self._shift, hl, len(self._hl_addrs),
                             time.time(), ok)
        with self._lock:
            self._snap = snap

    def snapshot(self) -> WhaleSnapshot:
        with self._lock:
            return self._snap

    def start(self):
        def loop():
            while not self._stop.is_set():
                self.poll_once()
                self._stop.wait(self.poll_s)
        threading.Thread(target=loop, daemon=True, name="WhaleWatcher").start()
        log.info(f"Whale watcher started (alert >= ${self.min_usd:,.0f}, poll {self.poll_s}s)")

    def stop(self):
        self._stop.set()
