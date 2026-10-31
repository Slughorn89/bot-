"""Dziennik bledow: wnioski bez reagowania na szum (sekcja 9.2).

Wpis powstaje, gdy model dal faktycznemu wynikowi < 10% (-ln p > 2.3).
Automat tylko PODPOWIADA klase:
  SZUM?          czerwona kartka (informacji nie bylo przed meczem) -> nic nie zmieniamy
  SLEPA_PLAMKA?  beniaminek na starcie sezonu, dluga przerwa, brak skladow: informacja mogla byc
                 dostepna przed meczem, a model jej nie mial -> backlog cech
  DO_OCENY       reszta: czlowiek sprawdza (sklady, kontuzje, rotacja, pogoda) i wpisuje final_class
Ceche z backlogu dodajemy dopiero, gdy ta sama slepa plamka wraca kilka razy i poprawia walidacje.
"""
from __future__ import annotations

import pandas as pd
import sqlalchemy as sa

from typer.store import db

THRESHOLD_LL = 2.3  # -ln(0.10)


def suggest(row) -> tuple[str, dict]:
    ctx = dict(wynik=f"{int(row.fthg)}:{int(row.ftag)}", p_actual=round(float(row.p_actual), 4),
               czerwone=dict(gosp=None if pd.isna(row.hr) else int(row.hr),
                             gosc=None if pd.isna(row.ar) else int(row.ar)))
    reds = (0 if pd.isna(row.hr) else row.hr) + (0 if pd.isna(row.ar) else row.ar)
    if reds > 0:
        return "SZUM?", ctx
    return "DO_OCENY", ctx


def update_journal(engine: sa.Engine, settled: pd.DataFrame) -> int:
    if settled.empty:
        return 0
    big = settled[(settled["outcome"] == 1) & (settled["log_loss"] > THRESHOLD_LL)]
    rows = []
    for r in big.itertuples(index=False):
        cls, ctx = suggest(r)
        ctx.update(mecz=f"{r.home} - {r.away}", liga=r.league, selekcja=r.selection,
                   wersja=r.model_version)
        rows.append(dict(prediction_id=int(r.prediction_id), event_id=r.event_id, market=r.market,
                         p_actual=float(r.p_actual), log_loss=float(r.log_loss), context=ctx,
                         suggested_class=cls))
    db.upsert(engine, db.error_journal, rows, ["prediction_id"], update=False)
    return len(rows)


def classify(engine: sa.Engine, entry_id: int, final_class: str, note: str = "") -> None:
    if final_class not in ("SZUM", "SLEPA_PLAMKA"):
        raise ValueError("final_class: SZUM albo SLEPA_PLAMKA")
    with engine.begin() as c:
        c.execute(db.error_journal.update().where(db.error_journal.c.id == entry_id)
                  .values(final_class=final_class, note=note))


def backlog(engine: sa.Engine) -> pd.DataFrame:
    """Powtarzajace sie slepe plamki (po notatce), kandydaci na nowe cechy."""
    j = db.read_df(engine, "SELECT note FROM error_journal WHERE final_class = 'SLEPA_PLAMKA'")
    if j.empty:
        return j
    return j.groupby("note").size().rename("ile").sort_values(ascending=False).reset_index()
