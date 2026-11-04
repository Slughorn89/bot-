"""Zbior meczow do backtestu i cyklu dziennego, z cache w data/.

Kolejnosc zrodel: football-data.co.uk (ma kursy zamkniecia), a jesli niedostepne, kopia xgabora.
Zrodla nie zgadujemy: jesli zadne nie dziala, rzucamy wyjatek z nazwa hosta.
"""
from __future__ import annotations

import logging
import pickle

import pandas as pd

from typer import config
from typer.ingest import xgabora
from typer.ingest.base import SourceUnavailable

log = logging.getLogger("typer.data")
CACHE = config.DATA_DIR / "matches.pkl"


def load_matches(since: str | None = None, refresh: bool = False, ref: str | None = None) -> pd.DataFrame:
    since = since or config.gates()["split"]["data_od"]
    ref = ref or config.sources()["xgabora"]["ref"]
    key = (since, ref)
    if CACHE.exists() and not refresh:
        with open(CACHE, "rb") as f:
            cached = pickle.load(f)
        if cached.get("key") == key:
            return cached["df"]
    try:
        df = xgabora.load(since=since, ref=ref)
    except SourceUnavailable as e:
        raise SourceUnavailable(f"brak danych historycznych: {e}") from e
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump({"key": key, "df": df}, f)
    return df


def split_dates() -> dict:
    s = config.gates()["split"]
    return {k: pd.Timestamp(v).date() for k, v in s.items()}
