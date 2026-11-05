"""Rozliczanie predykcji (tabela predictions jest niezmienialna, wiec rozliczenie to widok:
predictions JOIN results), log loss, CLV i eksport do formatu Zalacznika B dla evaluate.py."""
from __future__ import annotations

import numpy as np
import pandas as pd
import sqlalchemy as sa

from typer.betting.devig import devig_rows
from typer.metrics.kpi import SHARP_BOOKS
from typer.store import db

from typer import config

SQL_SETTLED = """
SELECT p.id AS prediction_id, p.event_id, p.market, p.selection, p.p_model, p.p_baseline,
       p.model_version, p.role, p.odds_taken, p.predicted_utc, p.kickoff_utc,
       e.league, e.sport, e.status, e.home, e.away, r.fthg, r.ftag, r.hr, r.ar
FROM predictions p
JOIN events e ON e.event_id = p.event_id
JOIN results r ON r.event_id = p.event_id
"""


def outcome(market: str, selection: str, gh: int, ga: int) -> int | None:
    if market == "1X2":
        res = "1" if gh > ga else "X" if gh == ga else "2"
        return int(selection == res)
    if market.startswith("OU"):
        line = float(market[2:])
        tot = gh + ga
        if abs(tot - line) < 1e-9:
            return None  # zwrot
        return int((tot > line) == selection.startswith("over"))
    if market == "BTTS":
        yes = gh > 0 and ga > 0
        return int(yes == (selection == "yes"))
    return None


def settled(engine: sa.Engine, role: str | None = "champion", since=None) -> pd.DataFrame:
    df = db.read_df(engine, SQL_SETTLED)
    if df.empty:
        return df
    void = set(config.sports().get("football", {}).get("void_statuses", []))
    df = df[~df["status"].isin(void)]  # void: przelozony/przerwany/odwolany nie wchodzi do oceny
    if role:
        df = df[df["role"] == role]
    if since is not None:
        df = df[pd.to_datetime(df["kickoff_utc"], utc=True) >= pd.Timestamp(since, tz="UTC")]
    # przy wielu predykcjach tej samej wersji na ten sam mecz liczy sie najwczesniejsza (bez poprawiania)
    df = df.sort_values("predicted_utc").drop_duplicates(["event_id", "market", "selection", "model_version"])
    df["outcome"] = [outcome(m, s, int(h), int(a)) for m, s, h, a in
                     zip(df["market"], df["selection"], df["fthg"], df["ftag"])]
    df = df.dropna(subset=["outcome"])
    df["outcome"] = df["outcome"].astype(int)
    # p, jakie model dal faktycznemu wynikowi danego rynku
    pa = df[df["outcome"] == 1].set_index(["event_id", "market", "model_version"])["p_model"]
    idx = pd.MultiIndex.from_frame(df[["event_id", "market", "model_version"]])
    df["p_actual"] = pa.reindex(idx).to_numpy()
    df["log_loss"] = -np.log(np.clip(df["p_actual"], 1e-12, 1))
    return df


def _devig_method(market: str) -> str:
    return (config.model_params().get("devig") or {}).get("zamkniecie", {}).get(market, "proportional")


def closing_odds(engine: sa.Engine, sharp_only: bool = True) -> pd.DataFrame:
    """Kurs zamkniecia per selekcja + kurs uczciwy (bez marzy), z JEDNEGO bukmachera na caly rynek.
    sharp_only (domyslnie): tylko ostry bukmacher (pinnacle); brak = brak wiersza, bez cichego zastepstwa
    miekkim kursem. Rynek bez kompletu selekcji u tego bukmachera odpada (marzy nie da sie zdjac)."""
    cols = ["event_id", "market", "selection", "odds_close", "odds_close_fair", "close_book"]
    sn = db.read_df(engine, "SELECT event_id, bookmaker, market, selection, price, snapshot_utc "
                            "FROM odds_snapshots WHERE kind = 'close'")
    if sn.empty:
        return pd.DataFrame(columns=cols)
    if sharp_only:
        sn = sn[sn["bookmaker"].isin(SHARP_BOOKS)]
    need = {"1X2": 3, "OU2.5": 2}
    sn = sn.sort_values("snapshot_utc").drop_duplicates(["event_id", "bookmaker", "market", "selection"], keep="last")
    out = []
    for (eid, mkt), g in sn.groupby(["event_id", "market"]):
        books = [b for b, gb in g.groupby("bookmaker") if len(gb) == need.get(mkt, len(gb))]
        if not books:
            continue
        book = sorted(books, key=lambda b: (b not in SHARP_BOOKS, b))[0]
        gb = g[g["bookmaker"] == book]
        fair = devig_rows(gb["price"].to_numpy(float)[None, :], _devig_method(mkt))[0]
        for (sel, price), f in zip(gb[["selection", "price"]].itertuples(index=False), fair):
            out.append(dict(event_id=eid, market=mkt, selection=sel, odds_close=price,
                            odds_close_fair=1 / f if f == f and f > 0 else np.nan, close_book=book))
    return pd.DataFrame(out, columns=cols)


def record_clv(engine: sa.Engine) -> int:
    """Dopisuje CLV dla zakladow, ktore maja juz ostre zamkniecie, a nie maja wiersza w bet_clv."""
    bets = db.read_df(engine, "SELECT id AS bet_id, event_id, market, selection, odds FROM bets")
    if bets.empty:
        return 0
    have = set(db.read_df(engine, "SELECT bet_id FROM bet_clv")["bet_id"])
    bets = bets[~bets["bet_id"].isin(have)]
    co = closing_odds(engine)
    b = bets.merge(co, on=["event_id", "market", "selection"]).dropna(subset=["odds_close_fair"])
    rows = [dict(bet_id=int(r.bet_id), event_id=r.event_id, market=r.market, selection=r.selection,
                 odds_taken=float(r.odds), close_odds=float(r.odds_close), close_odds_fair=float(r.odds_close_fair),
                 close_book=r.close_book, devig_method=_devig_method(r.market),
                 clv=float(r.odds / r.odds_close_fair - 1)) for r in b.itertuples(index=False)]
    db.append(engine, db.bet_clv, rows)
    return len(rows)


def export_preds(engine: sa.Engine, path, role: str = "champion", since=None, version: str | None = None
                 ) -> pd.DataFrame:
    """Plik w formacie Zalacznika B (z kursami zamkniecia, jesli sa) -> evaluate.py."""
    df = settled(engine, role=role, since=since)
    if version:
        df = df[df["model_version"] == version]
    if df.empty:
        pd.DataFrame(columns=["event_id", "date", "market", "selection", "p_model", "outcome"]).to_csv(path, index=False)
        return df
    co = closing_odds(engine)
    df = df.merge(co[["event_id", "market", "selection", "odds_close"]], how="left",
                  on=["event_id", "market", "selection"])
    bets = db.read_df(engine, "SELECT prediction_id, stake_frac FROM bets")
    df = df.merge(bets.rename(columns={"stake_frac": "stake"}), how="left", on="prediction_id")
    df["stake"] = df["stake"].fillna(0.0)
    df["date"] = pd.to_datetime(df["kickoff_utc"], utc=True).dt.strftime("%Y-%m-%d")
    cols = ["event_id", "date", "sport", "league", "market", "selection", "p_model", "outcome",
            "p_baseline", "odds_taken", "odds_close", "stake", "model_version"]
    out = df[cols]
    # odds_close musi byc dla calego rynku albo wcale (inaczej de-vig nie ma sensu)
    full = out.groupby(["event_id", "market"])["odds_close"].transform(lambda s: s.notna().all())
    out.loc[~full, "odds_close"] = np.nan
    if out["odds_close"].isna().all():
        out = out.drop(columns=["odds_close"])
    out.to_csv(path, index=False)
    return out
