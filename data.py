"""Historical OHLCV download with pagination and a CSV cache."""
import os
import time

import ccxt
import numpy as np
import pandas as pd

from backtest import TF_SECONDS


def fetch_history(exchange_id: str, symbol: str, timeframe: str, days: int,
                  cache_dir: str = "data") -> pd.DataFrame:
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{exchange_id}_{symbol.replace('/', '')}_{timeframe}.csv")
    ex = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    step = TF_SECONDS[timeframe] * 1000
    now = int(time.time() * 1000)
    since = now - days * 86_400_000
    frames = []
    if os.path.exists(path):
        cached = pd.read_csv(path, index_col=0, parse_dates=True)
        frames.append(cached)
        since = max(since, int(cached.index[-1].timestamp() * 1000) + step)
    rows = []
    while since < now:
        batch = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + step
        if len(batch) < 2:
            break
    if rows:
        new = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        new["timestamp"] = pd.to_datetime(new["timestamp"], unit="ms")
        frames.append(new.set_index("timestamp"))
    df = pd.concat(frames) if frames else pd.DataFrame()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.iloc[:-1]  # drop the still-forming candle
    df.to_csv(path)
    return df[df.index >= pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=days)]


def synthetic(days: int, timeframe: str, seed: int = 0) -> pd.DataFrame:
    """Random-walk OHLCV for smoke tests ONLY - proves nothing about profitability."""
    rng = np.random.default_rng(seed)
    n = int(days * 86_400 / TF_SECONDS[timeframe])
    ret = rng.normal(0.00002, 0.004, n)
    close = 30_000 * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[close[0]], close[:-1]])
    spread = np.abs(rng.normal(0, 0.003, n))
    idx = pd.date_range("2024-01-01", periods=n, freq=f"{TF_SECONDS[timeframe]}s")
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * (1 + spread),
                         "low": np.minimum(open_, close) * (1 - spread),
                         "close": close, "volume": rng.uniform(1, 10, n)}, index=idx)
