"""Klient HTTP warstwy danych: cache surowych odpowiedzi w raw/<zrodlo>/, limit zapytan,
ponawianie z wykladniczym opoznieniem (2, 4, 8, 16 s) z rozrzutem, 429 z Retry-After, audyt pobran.

Zasady:
  * bledy trwale (4xx poza 408 i 429, w tym 402 = brak tokenow/limitu) i odmowa proxy (polityka sieci)
    nie sa ponawiane; odpowiedz z bledem nigdy nie trafia do cache,
  * gdy zrodlo nie dziala, a jest stary cache, uzywamy go i to zapisujemy, nigdy nie zgadujemy danych,
  * fetched_at odpowiedzi z cache = chwila pierwotnego pobrania (mtime pliku), nie "teraz".
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

from typer.config import RAW_DIR

log = logging.getLogger("typer.ingest.http")


class SourceUnavailable(RuntimeError):
    """Zrodlo nie odpowiada albo odmawia dostepu. Zglaszamy, nie zgadujemy danych."""


class QuotaExhausted(SourceUnavailable):
    """HTTP 402: skonczyly sie tokeny albo limit planu. Ponawianie nic nie da, czekamy na reset."""


def _error_code(r) -> str:
    """Kod bledu z ciala JSON ({"error": {"code": ...}}), pusty, gdy go nie ma."""
    try:
        err = r.json().get("error") or {}
        return str(err.get("code") or err.get("message") or "") if isinstance(err, dict) else str(err)
    except (ValueError, AttributeError):
        return ""


@dataclass
class Response:
    content: bytes
    fetched_at: datetime
    from_cache: bool
    headers: dict = field(default_factory=dict)
    path: Path | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _retry_after(headers) -> float | None:
    v = (headers or {}).get("Retry-After")
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


class HttpClient:
    def __init__(self, source: str, *, limiter=None, session: requests.Session | None = None,
                 raw_dir: Path | None = None, retries: int = 4, base_delay: float = 2.0,
                 jitter: float = 0.1, timeout: float = 60, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], datetime] = _now, rng: random.Random | None = None):
        self.source, self.limiter = source, limiter
        self.session = session or requests.Session()
        self.raw_dir = raw_dir or RAW_DIR
        self.retries, self.base_delay, self.jitter, self.timeout = retries, base_delay, jitter, timeout
        self.sleep, self.clock = sleep, clock
        self.rng = rng or random.Random(7)
        self.waits: list[float] = []   # opoznienia ponowien (do testow i logow)
        self.audit: list[dict] = []    # wiersze do tabeli raw_fetches

    def _path(self, cache_name: str) -> Path:
        return self.raw_dir / self.source / cache_name

    def _log(self, url, params, status, resp: Response | None, note=""):
        h = hashlib.sha256(json.dumps(params or {}, sort_keys=True, default=str).encode()).hexdigest()[:16]
        self.audit.append(dict(source=self.source, url=url, params_hash=h, status=status,
                               fetched_at=resp.fetched_at if resp else self.clock(),
                               from_cache=bool(resp and resp.from_cache),
                               path=str(resp.path) if resp and resp.path else None,
                               sha256=hashlib.sha256(resp.content).hexdigest() if resp else None,
                               bytes=len(resp.content) if resp else 0, note=note))

    def _cached(self, path: Path) -> Response:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        return Response(path.read_bytes(), mtime, True, {}, path)

    def get(self, url: str, cache_name: str, *, params: dict | None = None, headers: dict | None = None,
            max_age_hours: float | None = 24, method: str = "GET", json_body=None) -> Response:
        """max_age_hours=None: cache bezterminowy (np. przypiety commit); 0: zawsze pobieraj."""
        path = self._path(cache_name)
        if path.exists() and max_age_hours is not None and max_age_hours > 0:
            age_h = (time.time() - path.stat().st_mtime) / 3600
            if age_h < max_age_hours:
                resp = self._cached(path)
                self._log(url, params, "cache", resp)
                return resp
        elif path.exists() and max_age_hours is None:
            resp = self._cached(path)
            self._log(url, params, "cache", resp)
            return resp
        last_err = None
        for attempt in range(self.retries + 1):
            if self.limiter is not None:
                self.limiter.acquire()
            try:
                r = self.session.request(method, url, params=params, headers=headers, json=json_body,
                                         timeout=self.timeout)
                if r.status_code in (408, 429) or r.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
                if r.status_code >= 400:
                    # bledy trwale: ponawianie nic nie da, a cialo bledu nie moze trafic do cache
                    code = _error_code(r)
                    self._log(url, params, f"http {r.status_code}", None, note=code)
                    msg = f"{self.source}: HTTP {r.status_code}{' ' + code if code else ''} dla {url}"
                    if r.status_code == 402:
                        h = dict(r.headers or {})
                        raise QuotaExhausted(f"{msg} (zostalo {h.get('X-Tokens-Remaining', '?')}, "
                                             f"reset {h.get('X-Tokens-Reset', '?')})")
                    raise SourceUnavailable(msg)
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(path.suffix + ".part")
                tmp.write_bytes(r.content)
                tmp.replace(path)  # zapis atomowy
                resp = Response(r.content, self.clock(), False, dict(r.headers), path)
                self._log(url, params, f"http {r.status_code}", resp)
                return resp
            except SourceUnavailable:
                raise
            except requests.exceptions.ProxyError as e:
                # odmowa proxy to polityka sieci, nie chwilowy blad: bez ponawiania
                if path.exists():
                    log.error("%s zablokowane przez proxy, uzywam starego cache %s", self.source, path)
                    resp = self._cached(path)
                    self._log(url, params, "proxy-denied, stary cache", resp)
                    return resp
                self._log(url, params, "proxy-denied", None)
                raise SourceUnavailable(f"{self.source}: host zablokowany przez proxy ({e})") from e
            except requests.RequestException as e:  # siec, 5xx, 429
                last_err = e
                if attempt >= self.retries:
                    break
                delay = self.base_delay * (2 ** attempt)
                delay *= 1 + self.rng.uniform(-self.jitter, self.jitter)
                ra = _retry_after(getattr(getattr(e, "response", None), "headers", None))
                if ra is not None:
                    delay = max(delay, ra)  # zrodlo mowi, ile czekac: nie szybciej
                log.warning("%s: proba %d nieudana (%s), ponawiam za %.1fs", self.source, attempt + 1, e, delay)
                self.waits.append(delay)
                self.sleep(delay)
        if path.exists():
            log.error("%s niedostepne (%s), uzywam starego cache %s", self.source, last_err, path)
            resp = self._cached(path)
            self._log(url, params, "blad, stary cache", resp)
            return resp
        self._log(url, params, f"blad: {last_err}", None)
        raise SourceUnavailable(f"{self.source}: {last_err}")
