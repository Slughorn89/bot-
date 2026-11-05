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
CACHE_EXT = config.DATA_DIR / "matches_ext.pkl"
# zmiana parsera (np. naprawa nazw) = nowy klucz cache, zeby nie czytac starych, blednych danych
PARSER_VERSION = 2


def load_matches(since: str | None = None, refresh: bool = False, ref: str | None = None,
                 extended: bool = False) -> pd.DataFrame:
    """extended=True: dodatkowo rozne, faule, kartki (schema.EXTRA_COLS), osobny plik cache."""
    since = since or config.gates()["split"]["data_od"]
    ref = ref or config.sources()["xgabora"]["ref"]
    key = (since, ref, PARSER_VERSION, str(config.load_yaml("aliases.yaml")), extended)
    cache = CACHE_EXT if extended else CACHE
    if cache.exists() and not refresh:
        with open(cache, "rb") as f:
            cached = pickle.load(f)
        if cached.get("key") == key:
            return cached["df"]
    try:
        df = xgabora.load(since=since, ref=ref, extended=extended)
    except SourceUnavailable as e:
        raise SourceUnavailable(f"brak danych historycznych: {e}") from e
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(cache, "wb") as f:
        pickle.dump({"key": key, "df": df}, f)
    return df


def split_dates() -> dict:
    s = config.gates()["split"]
    return {k: pd.Timestamp(v).date() for k, v in s.items()}
