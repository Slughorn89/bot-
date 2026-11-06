"""Prawdziwe xG z lokalnej kopii TheStatsAPI (data/thestatsapi_{liga}_{sezon}.pkl) dolaczone do meczow.

xG meczu jest dostepne dopiero po meczu, a silnik ocen online uzywa go tylko w aktualizacji po meczu
(nigdy w predykcji tego samego meczu), wiec dolaczenie do ramki nie tworzy wycieku. Brak xG (mecz
niepobrany, sezon bez xG) = NaN, a silnik wraca wtedy do przyblizenia ze strzalow.
"""
from __future__ import annotations

import pickle

import pandas as pd

from typer import config
from typer.entities.mapping import resolve_many


def load_cached(league: str) -> pd.DataFrame:
    """Kolumny: src_home, src_away, kickoff_utc, xg_h, xg_a (nazwy jak w zrodle)."""
    parts = []
    for f in sorted(config.DATA_DIR.glob(f"thestatsapi_{league}_*.pkl")):
        rec = pd.DataFrame(pickle.load(open(f, "rb")))
        if "_type" not in rec or "xg" not in rec:
            continue
        st = rec[rec["_type"] == "TeamMatchStats"]
        k = ["home", "away", "kickoff_utc"]
        h = st[st["side"] == "home"][k + ["xg"]].rename(columns={"xg": "xg_h"})
        a = st[st["side"] == "away"][k + ["xg"]].rename(columns={"xg": "xg_a"})
        parts.append(h.merge(a, on=k).rename(columns={"home": "src_home", "away": "src_away"}))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
        columns=["src_home", "src_away", "kickoff_utc", "xg_h", "xg_a"])


def attach(df: pd.DataFrame, xg_by_league: dict[str, pd.DataFrame] | None = None) -> tuple[pd.DataFrame, list]:
    """Dolacza xg_h, xg_a po (liga, gospodarz, gosc, data). Zwraca (ramka, niedopasowane nazwy)."""
    out, pending_all = [], []
    for lg, g in df.groupby("league", sort=False):
        xg = (xg_by_league or {}).get(lg)
        xg = load_cached(lg) if xg is None else xg.copy()
        g = g.drop(columns=[c for c in ("xg_h", "xg_a") if c in g])
        if xg.empty:
            out.append(g.assign(xg_h=float("nan"), xg_a=float("nan")))
            continue
        teams = sorted(set(g["home"]) | set(g["away"]))
        mp, pending = resolve_many(sorted(set(xg["src_home"]) | set(xg["src_away"])), teams)
        pending_all += [m.raw for m in pending]
        xg["home"], xg["away"] = xg["src_home"].map(mp), xg["src_away"].map(mp)
        xg["date"] = pd.to_datetime(xg["kickoff_utc"]).dt.date
        xg = (xg.dropna(subset=["home", "away"])[["home", "away", "date", "xg_h", "xg_a"]]
              .drop_duplicates(["home", "away", "date"]))
        m = g.reset_index().merge(xg, on=["home", "away", "date"], how="left").set_index("index")
        out.append(m)
    res = pd.concat(out).loc[df.index] if out else df.assign(xg_h=float("nan"), xg_a=float("nan"))
    return res, pending_all
