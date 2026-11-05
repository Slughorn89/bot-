"""Limit zapytan na minute (token bucket) per zrodlo. Limity dzienne/miesieczne (kredyty) pilnuje
osobno typer/ingest/budget.py. Zegar i sleep sa wstrzykiwane, wiec testy nie czekaja naprawde."""
from __future__ import annotations

import threading
import time
from typing import Callable

from typer import config


class TokenBucket:
    def __init__(self, rate: float, per_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        if rate <= 0 or per_seconds <= 0:
            raise ValueError("rate i per_seconds musza byc dodatnie")
        self.capacity = float(rate)
        self.tokens = float(rate)
        self.fill = rate / per_seconds
        self.clock, self.sleep = clock, sleep
        self.last = clock()
        self.waited = 0.0
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.fill)
        self.last = now

    def acquire(self, n: float = 1.0) -> float:
        """Czeka, az bedzie n zetonow. Zwraca czas oczekiwania w sekundach."""
        with self._lock:
            self._refill()
            wait = 0.0
            if self.tokens < n:
                wait = (n - self.tokens) / self.fill
                self.sleep(wait)
                self.waited += wait
                self._refill()
                self.tokens = max(self.tokens, n)  # po odczekaniu zeton jest nasz
            self.tokens -= n
            return wait


_LIMITERS: dict[str, TokenBucket] = {}


def limiter_for(source: str) -> TokenBucket | None:
    """Limiter z config/sources.yaml: <zrodlo>.limit_na_minute. Brak wpisu = brak limitu na minute."""
    if source in _LIMITERS:
        return _LIMITERS[source]
    rate = (config.sources().get(source) or {}).get("limit_na_minute")
    if not rate:
        return None
    _LIMITERS[source] = TokenBucket(float(rate), 60.0)
    return _LIMITERS[source]
