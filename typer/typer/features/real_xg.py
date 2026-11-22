"""Prawdziwe xG z lokalnej kopii TheStatsAPI (data/thestatsapi_{liga}_{sezon}.pkl) dolaczone do meczow.

xG meczu jest dostepne dopiero po meczu, a silnik ocen online uzywa go tylko w aktualizacji po meczu
(nigdy w predykcji tego samego meczu), wiec dolaczenie do ramki nie tworzy wycieku. Brak xG (mecz
niepobrany, sezon bez xG) = NaN, a silnik wraca wtedy do przyblizenia ze strzalow.
"""
from __future__ import annotations

import json
import pickle
from datetime import datetime, timedelta, timezone

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
        xg = (xg.dropna(subset=["home", "away", "xg_h", "xg_a"])[["home", "away", "date", "xg_h", "xg_a"]]
              .drop_duplicates(["home", "away", "date"]))
        m = g.reset_index().merge(xg, on=["home", "away", "date"], how="left").set_index("index")
        out.append(m)
    res = pd.concat(out).loc[df.index] if out else df.assign(xg_h=float("nan"), xg_a=float("nan"))
    return res, pending_all


LIVE_LAG = timedelta(hours=6)       # xG pojawia sie w zrodle z opoznieniem; mlodszych meczow nie pytamy


def _live_path(league: str):
    return config.DATA_DIR / f"thestatsapi_{league}_live.pkl"


def refresh(league: str, days: int = 7, now: datetime | None = None, ledger=None) -> dict:
    """Dociaga statystyki (xG) meczow rozegranych w ostatnich `days` dniach do data/thestatsapi_{liga}_live.pkl.

    Koszt: 1 zapytanie o liste + 1 na kazdy nowy mecz. Mecze, ktore juz maja xG w kopii, sa pomijane; mecz bez
    xG jest pytany ponownie (kopia w cache starsza niz 12 h), bo zrodlo uzupelnia xG z opoznieniem.
    Rekordy maja available_at z adaptera (po meczu), wiec do predykcji tego meczu nie trafia."""
    from typer.ingest import thestatsapi as api
    from typer.ingest.adapters.thestatsapi import TheStatsAPI
    from typer.ingest.core.adapter import RawPayload
    now = now or datetime.now(timezone.utc)
    cid = (config.sources()["thestatsapi"].get("ligi") or {})[league]
    path = _live_path(league)
    old = pickle.load(open(path, "rb")) if path.exists() else []
    have = {r["source_key"].split(":")[0] for r in old
            if r.get("_type") == "TeamMatchStats" and r.get("xg") is not None and r.get("xg") == r.get("xg")}
    ms = api.matches(cid, None, date_from=(now - timedelta(days=days)).date().isoformat(),
                     date_to=now.date().isoformat(), ledger=ledger)
    ad, new, asked = TheStatsAPI(), [], 0
    for m in ms:
        if str(m["id"]) in have or pd.Timestamp(m["utc_date"]) > pd.Timestamp(now - LIVE_LAG):
            continue
        b = json.loads(api.match_bundle(m["id"], parts=("/stats",), ledger=ledger, max_age_hours=12))
        asked += 1
        m = dict(m)
        m.setdefault("competition_id", cid)
        b["match"] = m
        new += [r.model_dump() | {"_type": type(r).__name__}
                for r in ad.parse(RawPayload(f"{m['id']}.json", json.dumps(b).encode(), now, dict(league=league)))]
    if new:
        keys = {r["source_key"] for r in new}
        merged = [r for r in old if r["source_key"] not in keys] + new
        with open(path, "wb") as f:
            pickle.dump(merged, f)
    n_xg = sum(1 for r in new if r["_type"] == "TeamMatchStats" and r.get("xg") is not None) // 2
    return dict(liga=league, mecze_w_oknie=len(ms), zapytane=asked, z_xg=n_xg)
