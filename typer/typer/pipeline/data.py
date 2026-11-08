"""Zbior meczow do backtestu i cyklu dziennego, z cache w data/.

Baza: przypieta kopia xgabora (powtarzalny backtest, dane do 2026-09-03). Cykl dzienny (recent=True)
dokleja mecze rozegrane po koncu kopii z biezacych plikow football-data.co.uk (te same nazwy druzyn),
inaczej model nie widzi meczow z ostatnich tygodni, a settle nie dostaje wynikow.
Zrodla nie zgadujemy: jesli baza nie dziala, rzucamy wyjatek z nazwa hosta.
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
PARSER_VERSION = 2


def load_matches(since: str | None = None, refresh: bool = False, ref: str | None = None,
                 extended: bool = False, recent: bool = False) -> pd.DataFrame:
    """extended=True: dodatkowo rozne, faule, kartki (schema.EXTRA_COLS), osobny plik cache.
    recent=True (cykl dzienny): plus mecze po koncu kopii xgabora z football-data.co.uk;
    refresh=True pobiera je od nowa (pliki zmieniaja sie po kazdej kolejce)."""
    base = _load_base(since, ref, extended, refresh=refresh and (ref or config.sources()["xgabora"]["ref"]) == "main")
    if not recent:
        return base
    return add_recent(base, refresh=refresh, extended=extended)


def _load_base(since, ref, extended, refresh: bool = False) -> pd.DataFrame:
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


def _season_of(d) -> str:
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def add_recent(base: pd.DataFrame, refresh: bool = False, extended: bool = False,
               today=None) -> pd.DataFrame:
    """Dokleja mecze rozegrane po ostatniej dacie bazy (per liga) z football-data.co.uk.
    Bez sieci zostaje sama baza, z ostrzezeniem w logu (cykl dzienny i tak alarmuje o starych danych)."""
    from datetime import date
    from typer.entities.history import harmonize
    from typer.ingest import footballdata_uk as fd
    from typer.ingest import schema
    today = today or date.today()
    last = base.groupby("league")["date"].max().to_dict() if len(base) else {}
    leagues = config.leagues()
    main_last = [last[lg] for lg, m in leagues.items() if lg in last and m.get("fduk", {}).get("kind") != "new"]
    first = min(main_last) if main_last else today
    seasons, y = [], int(_season_of(first)[:4])
    while y <= int(_season_of(today)[:4]):
        seasons.append(f"{y}-{str(y + 1)[2:]}")
        y += 1
    try:
        new = fd.load(seasons, leagues, max_age_hours=1 if refresh else 24, extended=extended)
    except (SourceUnavailable, schema.ContractError) as e:
        log.warning("football-data.co.uk niedostepne, historia tylko do %s: %s", max(last.values(), default="?"), e)
        return base
    keep = pd.Series(True, index=new.index)
    for lg, d in last.items():
        keep &= ~((new["league"] == lg) & (pd.to_datetime(new["date"]) <= pd.Timestamp(d)))
    new = new[keep & ~new["event_id"].isin(set(base["event_id"]))]
    if new.empty:
        return base
    # kursy POL z football-data to zamkniecia, jak w bazie trzymamy je tylko jako benchmark rynku
    for lg, meta in leagues.items():
        if meta.get("odds_timing", "prematch") != "prematch":
            m = new["league"] == lg
            for s in ("h", "d", "a"):
                new.loc[m, f"bench_{s}"] = new.loc[m, f"bench_{s}"].fillna(new.loc[m, f"close_{s}"])
            new.loc[m, ["odds_h", "odds_d", "odds_a", "odds_o25", "odds_u25"]] = np.nan
    cols = list(base.columns)
    for c in cols:
        if c not in new.columns:
            new[c] = np.nan
    out = pd.concat([base, new[cols]], ignore_index=True)
    out = harmonize(out, config.load_yaml("aliases.yaml"))
    out["event_id"] = [schema.make_event_id(l, d, h, a)
                       for l, d, h, a in zip(out["league"], out["date"], out["home"], out["away"])]
    out = out.drop_duplicates("event_id", keep="first")
    return out.sort_values(["kickoff_utc", "league", "home"], kind="stable").reset_index(drop=True)


def freshness(df: pd.DataFrame, today=None) -> dict:
    """Ostatnia data meczu per liga i ile dni temu (do alarmu o nieaktualnej historii)."""
    from datetime import date
    today = today or date.today()
    if df.empty:
        return {}
    return {lg: (str(d), (today - d).days) for lg, d in df.groupby("league")["date"].max().items()}


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
