"""Kurs w chwili typu: tylko bukmacher zakladu (Betclic), bez mieszania bukmacherow miedzy selekcjami."""
from datetime import datetime, timezone

from typer.pipeline import daily
from typer.store import db


def test_taken_odds_only_from_configured_bookmaker(tmp_engine):
    ko = datetime(2026, 11, 23, 15, tzinfo=timezone.utc)
    db.upsert(tmp_engine, db.events, [dict(event_id="e1", sport="football", league="E0", season="2026-27",
                                           kickoff_utc=ko, home="Arsenal", away="Chelsea", status="scheduled")],
              ["event_id"], update=False)
    t0, t1 = datetime(2026, 11, 23, 9, tzinfo=timezone.utc), datetime(2026, 11, 23, 10, tzinfo=timezone.utc)
    rows = []
    for book, t, prices in (("betclic_fr", t0, (2.0, 3.4, 3.9)), ("marathonbet", t1, (2.3, 3.6, 4.4))):
        for sel, p in zip(("1", "X", "2"), prices):
            rows.append(dict(event_id="e1", source="the_odds_api", bookmaker=book, market="1X2", selection=sel,
                             price=p, kind="taken", snapshot_utc=t))
    db.upsert(tmp_engine, db.odds_snapshots, rows, ["event_id", "source", "bookmaker", "market", "selection",
                                                    "snapshot_utc"], update=False)
    fx = daily._fixtures_from_db(tmp_engine, "2026-11-23")
    r = fx.iloc[0]
    assert (r["odds_h"], r["odds_d"], r["odds_a"]) == (2.0, 3.4, 3.9)   # Betclic, choc Marathon jest nowszy
