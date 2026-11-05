"""Zbior meczow do backtestu i cyklu dziennego, z cache w data/.

Baza: kopia xgabora (historia od 2005, Ekstraklasa). Do niej z football-data.co.uk (oryginal albo
lustro z GitHuba, po kontroli zgodnosci) doklejamy kursy zamkniecia i mecze po koncu xgabora.
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


def load_matches(since: str | None = None, refresh: bool = False, ref: str | None = None,
                 use_fduk: bool | None = None) -> pd.DataFrame:
    """Historia xgabora + (opcjonalnie) kursy zamkniecia i nowe mecze z football-data / lustra."""
    since = since or config.gates()["split"]["data_od"]
    ref = ref or config.sources()["xgabora"]["ref"]
    lustro = config.sources().get("fduk_lustro", {})
    if use_fduk is None:
        use_fduk = bool(lustro)
    key = (since, ref, lustro.get("ref") if use_fduk else None,
           config.model_params().get("zamkniecie", "B365") if use_fduk else None)
    if CACHE.exists() and not refresh:
        with open(CACHE, "rb") as f:
            cached = pickle.load(f)
        if cached.get("key") == key:
            return cached["df"]
    try:
        df = xgabora.load(since=since, ref=ref)
    except SourceUnavailable as e:
        raise SourceUnavailable(f"brak danych historycznych: {e}") from e
    if use_fduk:
        from typer.ingest import merge
        df, rep = merge.enrich(df, merge.load_fduk())
        log.info("football-data dolaczone: %s", rep)
        LAST_MERGE.clear()
        LAST_MERGE.update(rep)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump({"key": key, "df": df}, f)
    return df


LAST_MERGE: dict = {}


def split_dates() -> dict:
    s = config.gates()["split"]
    return {k: pd.Timestamp(v).date() for k, v in s.items()}
