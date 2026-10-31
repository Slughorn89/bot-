"""Pobieranie z cache surowych odpowiedzi i ponawianiem z wykladniczym opoznieniem.

Surowe bajty trafiaja do raw/<zrodlo>/, parsowanie jest osobno, wiec nie pobieramy drugi raz.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from typer.config import RAW_DIR

log = logging.getLogger("typer.ingest")


class SourceUnavailable(RuntimeError):
    """Zrodlo nie odpowiada albo odmawia dostepu. Zglaszamy, nie zgadujemy danych."""


def fetch(url: str, source: str, filename: str, *, max_age_hours: float | None = 24,
          retries: int = 4, timeout: float = 60, params: dict | None = None,
          headers: dict | None = None, session: requests.Session | None = None,
          raw_dir: Path | None = None) -> bytes:
    """Zwraca bajty z cache (jesli swiezy) albo pobiera. max_age_hours=None = cache bezterminowy."""
    path = (raw_dir or RAW_DIR) / source / filename
    if path.exists() and (max_age_hours is None or
                          (time.time() - path.stat().st_mtime) < max_age_hours * 3600):
        log.info("cache: %s", path)
        return path.read_bytes()
    sess = session or requests.Session()
    delay, last_err = 2.0, None
    for attempt in range(retries + 1):
        try:
            r = sess.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code in (401, 403, 404):
                # bledy trwale: ponawianie nic nie da
                raise SourceUnavailable(f"{source}: HTTP {r.status_code} dla {url}")
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(r.content)
            tmp.replace(path)  # zapis atomowy: brak polowicznych plikow w cache
            log.info("pobrano %s (%d B)", url, len(r.content))
            return r.content
        except SourceUnavailable:
            raise
        except requests.exceptions.ProxyError as e:
            # odmowa proxy (np. 403 na CONNECT) to polityka sieci, nie chwilowy blad: nie ponawiamy
            if path.exists():
                log.error("%s zablokowane przez proxy, uzywam starego cache %s", source, path)
                return path.read_bytes()
            raise SourceUnavailable(f"{source}: host zablokowany przez proxy ({e})") from e
        except requests.RequestException as e:  # sieć, 5xx, 429
            last_err = e
            if attempt < retries:
                log.warning("%s: proba %d nieudana (%s), ponawiam za %.0fs", source, attempt + 1, e, delay)
                time.sleep(delay)
                delay *= 2
    if path.exists():
        log.error("%s niedostepne (%s), uzywam starego cache %s", source, last_err, path)
        return path.read_bytes()
    raise SourceUnavailable(f"{source}: {last_err}")
