import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest import run_backtest
from data import synthetic
from signals import STRATEGIES, atr, compute_signals, expand_grid
from strategy import OptimizedStrategy, Signal
from whales import WhaleWatcher, diff_positions, parse_positions, score_from


# ---------------------------------------------------------------- signals
def test_no_lookahead_in_any_strategy():
    """Signal at bar i must equal the signal computed with data truncated at bar i."""
    df = synthetic(120, "1h")
    for name in STRATEGIES:
        for p in expand_grid(name)[::41]:
            en_full, ex_full = compute_signals(name, df, p)
            for cut in range(len(df) - 400, len(df), 7):
                en_cut, ex_cut = compute_signals(name, df.iloc[:cut], p)
                assert en_cut.iloc[-1] == en_full.iloc[cut - 1], (name, p, cut)
                assert ex_cut.iloc[-1] == ex_full.iloc[cut - 1], (name, p, cut)


# ---------------------------------------------------------------- engine
def _flat(n, px=100.0):
    return [px] * n


def _run(o, h, l, c, entry_at, sl=2.0, tp=0.0, exit_at=None, atr_v=1.0):
    n = len(c)
    entry = [i == entry_at for i in range(n)]
    ex = [i == exit_at for i in range(n)]
    return run_backtest(o, h, l, c, [atr_v] * n, entry, ex, sl, tp,
                        risk=0.02, fee=0.0, slip=0.0, init=10_000, max_alloc=10.0)


def test_stop_loss_costs_exactly_the_risk():
    n = 6
    o, h, l, c = _flat(n), _flat(n), _flat(n), _flat(n)
    l[3] = 97.0  # stop at 100 - 2*1 = 98 -> touched in bar 3
    r = _run(o, h, l, c, entry_at=1)
    assert len(r.trades) == 1 and r.trades[0]["why"] == "stop"
    assert abs(r.trades[0]["pnl"] - (-200.0)) < 1e-6     # 2% of 10k
    assert abs(r.equity[-1] - 9_800.0) < 1e-6


def test_gap_through_stop_fills_at_open():
    n = 6
    o, h, l, c = _flat(n), _flat(n), _flat(n), _flat(n)
    o[3], h[3], l[3], c[3] = 90.0, 90.0, 90.0, 90.0
    r = _run(o, h, l, c, entry_at=1)
    assert r.trades[0]["why"] == "gap_stop" and r.trades[0]["exit"] == 90.0
    assert r.trades[0]["pnl"] < -200.0                      # worse than the planned risk


def test_stop_wins_when_stop_and_target_hit_same_bar():
    n = 6
    o, h, l, c = _flat(n), _flat(n), _flat(n), _flat(n)
    h[3], l[3] = 110.0, 95.0
    r = _run(o, h, l, c, entry_at=1, tp=3.0)
    assert r.trades[0]["why"] == "stop"


def test_take_profit_and_signal_exit():
    n = 8
    o, h, l, c = _flat(n), _flat(n), _flat(n), _flat(n)
    h[3] = 104.0
    r = _run(o, h, l, c, entry_at=1, tp=3.0)
    assert r.trades[0]["why"] == "tp" and r.trades[0]["exit"] == 103.0
    r2 = _run(o, h[:3] + [100.0] * 5, l, c, entry_at=1, exit_at=4)
    assert r2.trades[0]["why"] == "signal" and r2.trades[0]["exit_i"] == 5


def test_entry_uses_next_open_not_signal_close():
    n = 6
    o, h, l, c = _flat(n), _flat(n), _flat(n), _flat(n)
    o[2] = 101.0
    r = _run(o, h, l, c, entry_at=1)
    assert r.trades[0]["entry"] == 101.0 and r.trades[0]["entry_i"] == 2


def test_fees_reduce_pnl():
    n = 6
    o, h, l, c = _flat(n), _flat(n), _flat(n), _flat(n)
    r = run_backtest(o, h, l, c, [1.0] * n, [i == 1 for i in range(n)], [i == 3 for i in range(n)],
                     2.0, 0.0, risk=0.02, fee=0.001, slip=0.0, init=10_000, max_alloc=1.0)
    assert r.trades[0]["pnl"] < 0                            # flat price, only costs


# ---------------------------------------------------------------- whales
STATE = {"assetPositions": [{"position": {"coin": "BTC", "szi": "-12.5", "positionValue": "1250000.0"}},
                            {"position": {"coin": "ETH", "szi": "300", "positionValue": "900000"}}]}


def test_parse_positions_signs():
    assert parse_positions(STATE) == {"BTC": -1_250_000.0, "ETH": 900_000.0}


def test_diff_positions_events():
    ev = diff_positions("0xabc", {}, {"BTC": 2_000_000}, 1_000_000)
    assert [e["kind"] for e in ev] == ["OPENED_LONG"]
    assert diff_positions("0xabc", {"BTC": 2_000_000}, {}, 1_000_000)[0]["kind"] == "CLOSED"
    assert diff_positions("0xabc", {"BTC": 2_000_000}, {"BTC": -2_000_000}, 1_000_000)[0]["kind"] == "FLIPPED_SHORT"
    assert diff_positions("0xabc", {"BTC": 2_000_000}, {"BTC": 3_500_000}, 1_000_000)[0]["kind"] == "INCREASED"
    assert diff_positions("0xabc", {"BTC": 2_000_000}, {"BTC": 2_100_000}, 1_000_000) == []   # small change
    assert diff_positions("0xabc", {}, {"BTC": 300_000}, 1_000_000) == []                    # small position


def _watcher(events):
    return WhaleWatcher(None, "BTC/USDT", min_usd=1_000_000, flow_min_usd=100_000, on_event=events.append)


def test_tape_flow_dedup_and_alerts():
    ev, now = [], int(time.time() * 1000)
    w = _watcher(ev)
    trades = [{"id": 1, "timestamp": now, "side": "buy", "cost": 1_500_000, "price": 60000, "amount": 25},
              {"id": 2, "timestamp": now, "side": "sell", "cost": 200_000, "price": 60000, "amount": 3},
              {"id": 3, "timestamp": now, "side": "buy", "cost": 5_000, "price": 60000, "amount": 0.08}]
    w.ingest_trades(trades)
    w.ingest_trades(trades)                                   # duplicates ignored
    assert sum(v for _, v in w._trades) == 1_500_000 - 200_000   # small trade excluded from flow
    assert len(ev) == 1 and ev[0]["kind"] == "BIG_BUY"


def test_score_bounds_and_direction():
    assert -1 <= score_from(1e12, 1, 1, 1e12, 1e6) <= 1
    assert score_from(-5e6, -0.5, -0.5, -5e6, 1e6) < -0.3
    assert score_from(5e6, 0.5, 0.5, 5e6, 1e6) > 0.3
    assert score_from(0, 0, 0, 0, 1e6) == 0


# ---------------------------------------------------------------- strategy / bot
def test_optimized_strategy_hold_when_nothing_passed(tmp_path):
    p = tmp_path / "bp.json"
    p.write_text(json.dumps({"strategy": None, "note": "none passed"}))
    df = synthetic(30, "1h")
    assert OptimizedStrategy(str(p)).analyze(df).signal == Signal.HOLD


def test_optimized_strategy_buy_has_atr_distances(tmp_path):
    p = tmp_path / "bp.json"
    p.write_text(json.dumps({"strategy": "donchian",
                             "params": {"entry_n": 20, "exit_n": 10, "sl_atr": 2, "tp_atr": 3}}))
    df = synthetic(30, "1h")
    df.iloc[-1, df.columns.get_loc("close")] = df["high"].iloc[-21:-1].max() * 1.05
    df.iloc[-1, df.columns.get_loc("high")] = df["close"].iloc[-1]
    r = OptimizedStrategy(str(p)).analyze(df)
    a = atr(df).iloc[-1]
    assert r.signal == Signal.BUY
    assert abs(r.stop_distance - 2 * a) < 1e-9 and abs(r.target_distance - 3 * a) < 1e-9


def test_whale_filter_blocks_buy(tmp_path):
    from bot import TradingBot
    from config import Config
    from risk_manager import RiskManager
    from strategy import StrategyResult
    from trade_log import trade_log

    trade_log.path = str(tmp_path / "log.json")

    class Snap: score, flow_usd, updated_at = -0.6, -3e6, time.time()
    class FakeWhales:
        def snapshot(self): return Snap()
    class FakeStrategy:
        def analyze(self, df): return StrategyResult(Signal.BUY, "x", stop_distance=1.0)

    bot = TradingBot.__new__(TradingBot)
    bot.cfg, bot.pair = Config(), "BTC/USDT"
    bot.cfg.WHALE_MODE = "filter"
    bot.whales, bot.strategy = FakeWhales(), FakeStrategy()
    bot.risk = RiskManager(0.1, 0.02, 0.04, 3)
    bot._open_long = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not open"))
    bot._evaluate(synthetic(5, "1h"), 100.0)                  # must not raise
    bot.cfg.WHALE_MODE = "alert"
    opened = []
    bot._open_long = lambda *a, **k: opened.append(1)
    bot._evaluate(synthetic(5, "1h"), 100.0)
    assert opened == [1]


def test_size_by_risk_caps():
    assert RiskManager.size_by_risk(10_000, 100, 2, 0.02, 0.5) == 50       # risk-limited: 200/2=100 -> cap 50
    assert RiskManager.size_by_risk(10_000, 100, 20, 0.02, 0.5) == 10      # 200/20
    assert RiskManager.size_by_risk(10_000, 100, 0, 0.02, 0.5) == 0


from risk_manager import RiskManager  # noqa: E402
