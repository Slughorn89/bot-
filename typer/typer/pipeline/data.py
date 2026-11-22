"""Zbior meczow do backtestu i cyklu dziennego, z cache w data/.

Kolejnosc zrodel: football-data.co.uk (ma kursy zamkniecia), a jesli niedostepne, kopia xgabora.
Zrodla nie zgadujemy: jesli zadne nie dziala, rzucamy wyjatek z nazwa hosta.
"""
from __future__ import annotations

import logging
import pickle

import numpy as np
import pandas as pd

from typer import config
from typer.ingest import xgabora
from typer.ingest.base import SourceUnavailable

log = logging.getLogger("typer.data")
CACHE = config.DATA_DIR / "matches.pkl"
CACHE_EXT = config.DATA_DIR / "matches_ext.pkl"
# zmiana parsera (np. naprawa nazw) = nowy klucz cache, zeby nie czytac starych, blednych danych
PARSER_VERSION = 3   # 3: Ekstraklasa po 2024-10 z football-data.co.uk (nowe ligi)


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
    df = extend_new_leagues(df, extended=extended)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(cache, "wb") as f:
        pickle.dump({"key": key, "df": df}, f)
    return df


def extend_new_leagues(df: pd.DataFrame, extended: bool = False) -> pd.DataFrame:
    """Kopia xgabora konczy sie dla czesci lig wczesniej (Ekstraklasa: 2024-10). Dla lig z plikiem "nowe ligi"
    football-data.co.uk (sports.yaml: fduk.kind = new) dokladamy mecze PO ostatniej dacie z kopii; starszych nie
    ruszamy (te same mecze, inne kursy). Te pliki maja tylko zamkniecia: odds_* zostaja puste (bez wycieku).
    Zrodlo niedostepne = ostrzezenie i dane bez uzupelnienia (nie zgadujemy)."""
    from typer.ingest import footballdata_uk as fduk
    from typer.ingest import schema
    src = config.sources()["football_data_uk"]
    parts = [df]
    for lg, meta in config.leagues().items():
        f = meta.get("fduk", {})
        if f.get("kind") != "new":
            continue
        try:
            raw = fduk.fetch(src["url_nowe_ligi"].format(code=f["code"]), fduk.SOURCE, f"new_{f['code']}.csv",
                             max_age_hours=24)
            new = fduk.parse(raw, lg, kind="new", extended=extended)
        except (SourceUnavailable, schema.ContractError) as e:
            log.warning("%s: brak uzupelnienia z football-data.co.uk (%s)", lg, e)
            continue
        last = df.loc[df["league"] == lg, "date"].max()
        if pd.notna(last):
            new = new[new["date"] > last]
        if not meta.get("has_shots", True):
            new[["hs", "as_", "hst", "ast"]] = np.nan
        log.info("%s: +%d meczow z football-data.co.uk po %s", lg, len(new), last)
        parts.append(new[df.columns.intersection(new.columns)])
    out = pd.concat(parts, ignore_index=True)
    if len(parts) > 1:
        from typer.entities.history import harmonize
        out = harmonize(out, config.load_yaml("aliases.yaml"))
        out["event_id"] = [schema.make_event_id(l, d, h, a)
                           for l, d, h, a in zip(out["league"], out["date"], out["home"], out["away"])]
        out = out.drop_duplicates("event_id", keep="first").sort_values(
            ["kickoff_utc", "league", "home"], kind="stable").reset_index(drop=True)
    return out


def split_dates() -> dict:
    s = config.gates()["split"]
    return {k: pd.Timestamp(v).date() for k, v in s.items()}


CLOSE_COLS = ["close_h", "close_d", "close_a", "close_o25", "close_u25"]
CLOSE_CACHE = config.DATA_DIR / "closing_fduk.pkl"


def load_closing(first_season: int = 2012, refresh: bool = False) -> pd.DataFrame:
    """Kursy zamkniecia Pinnacle z football-data.co.uk (PSC*, PC>2.5/PC<2.5) per event_id, z cache.
    Tylko do oceny (CLV, porownanie z rynkiem); model i blend nigdy ich nie widza."""
    from datetime import date
    from typer.ingest import footballdata_uk as fd
    last = date.today().year if date.today().month >= 7 else date.today().year - 1
    seasons = [f"{y}-{str(y + 1)[2:]}" for y in range(first_season, last + 1)]
    key = (tuple(seasons), PARSER_VERSION, str(config.load_yaml("aliases.yaml")))
    if CLOSE_CACHE.exists() and not refresh:
        with open(CLOSE_CACHE, "rb") as f:
            c = pickle.load(f)
        if c.get("key") == key:
            return c["df"]
    df = fd.load(seasons)[["event_id"] + CLOSE_COLS].drop_duplicates("event_id", keep="last")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CLOSE_CACHE, "wb") as f:
        pickle.dump({"key": key, "df": df}, f)
    return df


def attach_closing(frame: pd.DataFrame, closing: pd.DataFrame | None = None) -> pd.DataFrame:
    """Dolacza zamkniecia Pinnacle (nadpisuje puste close_*), kolumna close_book = 'pinnacle' tam, gdzie sa."""
    closing = closing if closing is not None else load_closing()
    out = frame.drop(columns=[c for c in CLOSE_COLS if c in frame.columns]).merge(closing, on="event_id", how="left")
    out["close_book"] = np.where(out["close_h"].notna(), "pinnacle", None)
    return out
