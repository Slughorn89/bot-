"""Champion i challenger (sekcja 9.5): nowa wersja typuje w cieniu na tych samych zdarzeniach.
Awans tylko, gdy przedzial CI90 roznicy log loss (challenger - champion) jest ponizej zera
w sparowanym bootstrapie, na co najmniej 300 zdarzeniach, i bramki sa zaliczone."""
from __future__ import annotations

import numpy as np
import pandas as pd
import sqlalchemy as sa

from typer.store import db

MIN_EVENTS = 300


def paired_bootstrap(ll_a: np.ndarray, ll_b: np.ndarray, n: int = 2000, seed: int = 7
                     ) -> tuple[float, float, float]:
    """Srednia roznica (b - a) i jej CI90. Ujemna = b lepszy."""
    d = np.asarray(ll_b, float) - np.asarray(ll_a, float)
    if len(d) == 0:
        return np.nan, np.nan, np.nan
    idx = np.random.default_rng(seed).integers(0, len(d), (n, len(d)))
    m = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(m, 5)), float(np.percentile(m, 95))


def compare(settled: pd.DataFrame, champion: str, challenger: str, market: str | None = None) -> dict:
    """settled: wynik learn.settle.settled(role=None) z kolumnami model_version, log_loss."""
    s = settled[settled["outcome"] == 1]  # jeden wiersz na (zdarzenie, rynek, wersja)
    if market:
        s = s[s["market"] == market]
    a = s[s["model_version"] == champion].set_index(["event_id", "market"])["log_loss"]
    b = s[s["model_version"] == challenger].set_index(["event_id", "market"])["log_loss"]
    common = a.index.intersection(b.index)
    mean, lo, hi = paired_bootstrap(a.loc[common].to_numpy(), b.loc[common].to_numpy())
    return dict(n=len(common), roznica=mean, ci90=(lo, hi),
                awans=bool(len(common) >= MIN_EVENTS and hi < 0))


def register(engine: sa.Engine, version: str, role: str, params: dict, changes: str,
             validation: dict | None = None, drift_reference_date: str | None = None) -> None:
    db.upsert(engine, db.model_registry, [dict(version=version, role=role, params=params, changes=changes,
                                              validation=validation or {},
                                              drift_reference_date=drift_reference_date)], ["version"])


def current(engine: sa.Engine, role: str = "champion") -> dict | None:
    df = db.read_df(engine, "SELECT * FROM model_registry WHERE role = :r ORDER BY created_utc DESC", r=role)
    if df.empty:
        return None
    return df.iloc[0].to_dict()


def promote(engine: sa.Engine, challenger: str, reference_date: str) -> None:
    """Challenger -> champion, stary champion -> retired, nowa referencja dryfu = data wdrozenia."""
    with engine.begin() as c:
        c.execute(db.model_registry.update().where(db.model_registry.c.role == "champion")
                  .values(role="retired"))
        c.execute(db.model_registry.update().where(db.model_registry.c.version == challenger)
                  .values(role="champion", drift_reference_date=reference_date))
