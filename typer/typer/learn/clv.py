"""CLV (closing line value) zapisanych typow wzgledem kursu zamkniecia bez marzy.

CLV = kurs_wziety / kurs_zamkniecia_fair - 1. To estymata oczekiwanego zysku z zakladu: dodatni
srednio CLV na duzej probie to najlepszy dostepny dowod przewagi (ROI na tej samej probie to glownie
szum). Liczymy wzgledem dwoch punktow odniesienia:

* betfair: gielda Betfair (bookmaker="betfair_exchange") ze snapshotu tuz przed startem
  (kind="close"), zbieranego samemu, bo archiwum OddsRelay nie ma gield. Kurs fair = de-vig
  cen back calego rynku (marza gieldy jest mala, ale nie zerowa; prowizji od wygranej nie odejmujemy).
* bukmacherzy: konsensus bukmacherow UK z /v2/historical/closing (source="oddsrelay_hist"):
  kazdy bukmacher osobno bez marzy, potem mediana prawdopodobienstw. Slabszy punkt odniesienia,
  ale jest od razu (archiwum od 2026-10-17).

Glowne CLV = betfair, a gdy go brak dla danego typu, bukmacherzy (kolumna `benchmark` mowi ktory).
Rynek musi miec kursy wszystkich selekcji, inaczej de-vig nie ma sensu i typ zostaje bez CLV.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import sqlalchemy as sa

from typer.betting.core import devig
from typer.store import db

log = logging.getLogger("typer.learn.clv")
BETFAIR = "betfair_exchange"
HIST_SOURCE = "oddsrelay_hist"
N_SEL = {"1X2": 3}  # rynki O/U i BTTS maja 2 selekcje


def _n_sel(market: str) -> int:
    return N_SEL.get(market, 2)


def _fair_per_book(sn: pd.DataFrame) -> pd.DataFrame:
    """Ostatni snapshot per bukmacher x selekcja, de-vig per bukmacher x mecz x rynek (pelny rynek)."""
    if sn.empty:
        return pd.DataFrame(columns=["event_id", "bookmaker", "market", "selection", "p_fair"])
    sn = sn.sort_values("snapshot_utc").drop_duplicates(
        ["event_id", "bookmaker", "market", "selection"], keep="last")
    out = []
    for (eid, book, mkt), g in sn.groupby(["event_id", "bookmaker", "market"]):
        if len(g) != _n_sel(mkt) or (g["price"] <= 1).any():
            continue
        for sel, p in zip(g["selection"], devig(g["price"].to_numpy())):
            out.append(dict(event_id=eid, bookmaker=book, market=mkt, selection=sel, p_fair=float(p)))
    return pd.DataFrame(out, columns=["event_id", "bookmaker", "market", "selection", "p_fair"])


def closing_fair(engine: sa.Engine) -> pd.DataFrame:
    """Kurs zamkniecia fair per mecz x rynek x selekcja dla obu punktow odniesienia."""
    sn = db.read_df(engine, "SELECT event_id, source, bookmaker, market, selection, price, snapshot_utc "
                            "FROM odds_snapshots WHERE kind = 'close'")
    cols = ["event_id", "market", "selection", "close_betfair", "fair_betfair", "fair_books", "n_books"]
    if sn.empty:
        return pd.DataFrame(columns=cols)
    sn["snapshot_utc"] = pd.to_datetime(sn["snapshot_utc"], utc=True)
    bf = _fair_per_book(sn[sn["bookmaker"] == BETFAIR])
    raw_bf = (sn[sn["bookmaker"] == BETFAIR].sort_values("snapshot_utc")
              .drop_duplicates(["event_id", "market", "selection"], keep="last")
              [["event_id", "market", "selection", "price"]].rename(columns={"price": "close_betfair"}))
    bf = bf.drop(columns="bookmaker").rename(columns={"p_fair": "p_betfair"})
    books = _fair_per_book(sn[sn["source"] == HIST_SOURCE])
    if len(books):
        books = books.groupby(["event_id", "market", "selection"]).agg(
            p_books=("p_fair", "median"), n_books=("bookmaker", "nunique")).reset_index()
        # mediana per selekcja nie sumuje sie do 1: normalizujemy w obrebie rynku
        books["p_books"] /= books.groupby(["event_id", "market"])["p_books"].transform("sum")
    else:
        books = pd.DataFrame(columns=["event_id", "market", "selection", "p_books", "n_books"])
    keys = ["event_id", "market", "selection"]
    out = bf.merge(raw_bf, on=keys, how="outer").merge(books, on=keys, how="outer")
    out["fair_betfair"] = 1 / out["p_betfair"]
    out["fair_books"] = 1 / out["p_books"].astype(float)
    return out[cols]


SQL_TIPS = """
SELECT b.id AS bet_id, b.prediction_id, b.event_id, b.market, b.selection, b.odds AS odds_taken,
       b.stake_frac, b.placed_utc, p.p_model, p.model_version, p.role, p.kickoff_utc,
       e.league, e.home, e.away
FROM bets b
JOIN predictions p ON p.id = b.prediction_id
JOIN events e ON e.event_id = b.event_id
"""


def tips_clv(engine: sa.Engine, since=None, until=None, role: str | None = "champion") -> pd.DataFrame:
    """Zapisane typy (tabela bets) z CLV wzgledem Betfair, bukmacherow i glownym (`clv`)."""
    t = db.read_df(engine, SQL_TIPS)
    if t.empty:
        return t
    t["kickoff_utc"] = pd.to_datetime(t["kickoff_utc"], utc=True)
    if role:
        t = t[t["role"] == role]
    if since is not None:
        t = t[t["kickoff_utc"] >= pd.Timestamp(since, tz="UTC")]
    if until is not None:
        t = t[t["kickoff_utc"] < pd.Timestamp(until, tz="UTC")]
    t = t.merge(closing_fair(engine), on=["event_id", "market", "selection"], how="left")
    t["clv_betfair"] = t["odds_taken"] / t["fair_betfair"] - 1
    t["clv_books"] = t["odds_taken"] / t["fair_books"] - 1
    t["benchmark"] = np.where(t["clv_betfair"].notna(), "betfair",
                              np.where(t["clv_books"].notna(), "bukmacherzy", None))
    t["clv"] = t["clv_betfair"].fillna(t["clv_books"])
    return t.reset_index(drop=True)


def _boot_mean(x: np.ndarray, n: int = 2000, seed: int = 7) -> tuple[float, float]:
    if len(x) < 2:
        return (float("nan"), float("nan"))
    idx = np.random.default_rng(seed).integers(0, len(x), (n, len(x)))
    m = x[idx].mean(1)
    return float(np.percentile(m, 5)), float(np.percentile(m, 95))


def summarize(t: pd.DataFrame) -> dict:
    """Srednie CLV z CI90 (bootstrap), odsetek bijacych zamkniecie, CLV wazone stawka, rozbicia."""
    out = dict(typy=int(len(t)), z_clv=0)
    if t.empty or t["clv"].notna().sum() == 0:
        return out
    c = t.dropna(subset=["clv"])
    x = c["clv"].to_numpy(float)
    out.update(z_clv=int(len(c)), clv_sr=float(x.mean()), clv_ci90=_boot_mean(x),
               bije_zamkniecie=float((x > 0).mean()),
               clv_wazone_stawka=float(np.average(x, weights=c["stake_frac"]))
               if c["stake_frac"].sum() > 0 else None)
    for col in ("clv_betfair", "clv_books"):
        v = t[col].dropna().to_numpy(float)
        out[col] = dict(n=int(len(v)), sr=float(v.mean()) if len(v) else None,
                        ci90=_boot_mean(v) if len(v) else None)
    out["wg_benchmarku"] = c["benchmark"].value_counts().to_dict()
    for key in ("league", "market"):
        out[f"wg_{key}"] = {k: dict(n=int(len(g)), clv_sr=float(g["clv"].mean()))
                           for k, g in c.groupby(key)}
    return out


def _pct(v) -> str:
    return "brak" if v is None or v != v else f"{v:+.2%}"


def report_text(s: dict, min_n: int = 300) -> str:
    lines = [f"Raport CLV: {s['typy']} zapisanych typów, z kursem zamknięcia {s['z_clv']}"]
    if not s.get("z_clv"):
        lines.append("  brak kursów zamknięcia dla zapisanych typów (zbierz snapshoty Betfair "
                     "przed startem albo pobierz zamknięcia bukmacherów: cli.py closing)")
        return "\n".join(lines)
    lo, hi = s["clv_ci90"]
    lines.append(f"  CLV śr. {_pct(s['clv_sr'])} (CI90 {_pct(lo)} do {_pct(hi)}), "
                 f"bije zamknięcie {s['bije_zamkniecie']:.0%}, ważone stawką {_pct(s['clv_wazone_stawka'])}")
    for col, name in (("clv_betfair", "Betfair"), ("clv_books", "bukmacherzy UK")):
        d = s[col]
        lines.append(f"  vs {name}: n {d['n']}, CLV śr. {_pct(d['sr'])}")
    for key, name in (("wg_league", "liga"), ("wg_market", "rynek")):
        parts = [f"{k} {_pct(v['clv_sr'])} (n {v['n']})" for k, v in sorted(s[key].items())]
        lines.append(f"  {name}: " + ", ".join(parts))
    if s["z_clv"] < min_n:
        lines.append(f"  uwaga: {s['z_clv']} typów to za mało na wniosek (minimum {min_n}), "
                     "przedział ufności jest szeroki")
    return "\n".join(lines)


def report(engine: sa.Engine, since=None, until=None, role: str | None = "champion",
           csv_path: Path | None = None) -> tuple[str, dict, pd.DataFrame]:
    t = tips_clv(engine, since=since, until=until, role=role)
    s = summarize(t)
    if csv_path is not None and len(t):
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        t.to_csv(csv_path, index=False)
    return report_text(s), s, t


def store_live_close(engine: sa.Engine, snap: pd.DataFrame, bookmakers: tuple[str, ...] = (BETFAIR,)
                     ) -> dict:
    """Snapshot na zywo (wynik oddsrelay.parse) -> odds_snapshots: tylko wiersze kind="close"
    (0..10 min przed startem) wskazanych venue, domyslnie gieldy Betfair (cena back)."""
    if snap.empty:
        return dict(snapshots=0, unmatched=0)
    s = snap[(snap["kind"] == "close") & snap["bookmaker"].isin(bookmakers)]
    return store_closing(engine, s, source="oddsrelay")


def store_closing(engine: sa.Engine, closing: pd.DataFrame, max_shift_hours: float = 6,
                  source: str = HIST_SOURCE) -> dict:
    """Zamkniecia (wynik oddsrelay_closing.parse albo snapshot na zywo) -> odds_snapshots, z mapowaniem
    nazw na mecze w bazie. Mecz musi zgadzac sie obiema druzynami w jednej lidze i godzina startu."""
    from typer.entities.mapping import resolve_many
    if closing.empty:
        return dict(snapshots=0, unmatched=0)
    ev = db.read_df(engine, "SELECT event_id, league, home, away, kickoff_utc FROM events")
    ev["kickoff_utc"] = pd.to_datetime(ev["kickoff_utc"], utc=True)
    lo, hi = closing["kickoff_utc"].min(), closing["kickoff_utc"].max()
    pad = pd.Timedelta(hours=max_shift_hours)
    ev = ev[(ev["kickoff_utc"] >= lo - pad) & (ev["kickoff_utc"] <= hi + pad)]
    manual = db.read_df(engine, "SELECT league, raw_name, canonical FROM entity_map "
                                "WHERE source = :s AND status = 'manual'", s=source)
    pairs = closing[["source_event_id", "home_raw", "away_raw", "kickoff_utc"]].drop_duplicates("source_event_id")
    matched, maps = [], []
    for lg, evl in ev.groupby("league"):
        cands = sorted(set(evl["home"]) | set(evl["away"]))
        man = dict(manual.loc[manual["league"] == lg, ["raw_name", "canonical"]].to_numpy())
        mapping, _ = resolve_many(list(pairs["home_raw"]) + list(pairs["away_raw"]), cands, man)
        p = pairs.assign(home=pairs["home_raw"].map(mapping), away=pairs["away_raw"].map(mapping))
        p = p.dropna(subset=["home", "away"]).merge(evl, on=["home", "away"], suffixes=("", "_ev"))
        p = p[(p["kickoff_utc"] - p["kickoff_utc_ev"]).abs() <= pad]
        matched.append(p[["source_event_id", "event_id"]])
        used = set(p["home_raw"]) | set(p["away_raw"])
        maps += [dict(source=source, league=lg, raw_name=k, canonical=v, score=1.0, status="auto")
                 for k, v in mapping.items() if k in used]
    m = pd.concat(matched) if matched else pd.DataFrame(columns=["source_event_id", "event_id"])
    m = m.drop_duplicates("source_event_id", keep=False)  # dwa mecze pasuja = nie zgadujemy
    db.upsert(engine, db.entity_map, maps, ["source", "league", "raw_name"], update=False)
    j = closing.merge(m, on="source_event_id")
    rows = []
    for r in j.itertuples(index=False):
        when = getattr(r, "close_at", None) or getattr(r, "snapshot_utc", None)
        ts = pd.Timestamp(when) if when is not None and when == when else r.kickoff_utc
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        rows.append(dict(event_id=r.event_id, source=source, bookmaker=r.bookmaker, market=r.market,
                         selection=r.selection, price=r.price, kind="close",
                         snapshot_utc=ts.to_pydatetime()))
    db.upsert(engine, db.odds_snapshots, rows,
              ["event_id", "source", "bookmaker", "market", "selection", "snapshot_utc"], update=False)
    unmatched = int(pairs["source_event_id"].nunique() - m["source_event_id"].nunique())
    return dict(snapshots=len(rows), events=int(m["source_event_id"].nunique()), unmatched=unmatched)
