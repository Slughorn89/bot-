"""Pobieranie z cache surowych odpowiedzi i ponawianiem z wykladniczym opoznieniem.

Surowe bajty trafiaja do raw/<zrodlo>/, parsowanie jest osobno, wiec nie pobieramy drugi raz.
"""
from __future__ import annotations

import logging
from pathlib import Path

import requests

log = logging.getLogger("typer.ingest")


from typer.ingest.core.http import HttpClient, SourceUnavailable  # noqa: E402,F401  (jedna implementacja)
from typer.ingest.core.ratelimit import limiter_for  # noqa: E402


def fetch(url: str, source: str, filename: str, *, max_age_hours: float | None = 24,
          retries: int = 4, timeout: float = 60, params: dict | None = None,
          headers: dict | None = None, session: requests.Session | None = None,
          raw_dir: Path | None = None, meta: dict | None = None) -> bytes:
    """Zwraca bajty z cache (jesli swiezy) albo pobiera. max_age_hours=None = cache bezterminowy.
    meta (opcjonalnie): dostaje 'cache', 'headers' i 'fetched_at' odpowiedzi.
    Cienka nakladka na typer.ingest.core.http.HttpClient (cache, limit, backoff, audyt)."""
    client = HttpClient(source, limiter=limiter_for(source), session=session, raw_dir=raw_dir,
                        retries=retries, timeout=timeout)
    resp = client.get(url, filename, params=params, headers=headers, max_age_hours=max_age_hours)
    if meta is not None:
        meta.update(cache=resp.from_cache, headers=resp.headers, fetched_at=resp.fetched_at)
    return resp.content
