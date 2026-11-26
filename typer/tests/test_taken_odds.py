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


def test_odds_api_events_fallback_maps_names_and_skips_unknown(monkeypatch):
    import json as _json
    from typer.ingest import odds_api
    monkeypatch.setenv("ODDS_API_KEY", "test")
    evs = [dict(id="1", commence_time="2026-11-27T20:00:00Z", home_team="Nottingham Forest", away_team="Chelsea"),
           dict(id="2", commence_time="2026-11-28T15:00:00Z", home_team="Nieznany FC", away_team="Chelsea")]
    monkeypatch.setattr(odds_api, "fetch", lambda url, *a, **k: _json.dumps(evs if "soccer_epl" in url else []).encode())
    df = odds_api.load_events({"E0": ["Nott'm Forest", "Chelsea", "Arsenal"]},
                              now=datetime(2026, 11, 26, 11, tzinfo=timezone.utc))
    assert list(zip(df["home"], df["away"])) == [("Nott'm Forest", "Chelsea")]   # nieznana nazwa pominieta
    assert df["fthg"].isna().all() and df["odds_h"].isna().all()
