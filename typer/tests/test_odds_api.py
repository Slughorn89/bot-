"""The Odds API: parser snapshotu i zapis kursow zamkniecia z mapowaniem nazw (bez sieci)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from typer.ingest import odds_api

FIX = Path(__file__).parent / "fixtures" / "odds_api_sample.json"


def _raw(home, away):
    return FIX.read_text().replace("HOME_PLACEHOLDER", home).replace("AWAY_PLACEHOLDER", away).encode()


def test_parser_snapshotu():
    snap = odds_api.parse(_raw("A", "B"), "E0", datetime(2018, 9, 8, 14, 55, tzinfo=timezone.utc))
    assert set(snap["market"]) == {"1X2", "OU2.5"}
    assert set(snap.loc[snap["market"] == "1X2", "selection"]) == {"1", "X", "2"}
    assert (snap["kind"] == "close").all()  # 5 minut przed startem = zamkniecie
    best = odds_api.best_price(snap)
    assert best.loc[best["selection"] == "2", "price"].item() == 3.70


def test_snapshot_do_bazy_z_mapowaniem(monkeypatch, tmp_engine, synth, tmp_path):
    from typer.pipeline import daily
    from typer.store import db
    monkeypatch.setattr(daily, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(daily, "ALERTS", tmp_path / "alerts.json")
    d = pd.Timestamp("2018-09-08").date()
    fx = synth[synth["date"] == d].head(1).copy()
    fx[["fthg", "ftag"]] = float("nan")
    db.store_matches(tmp_engine, fx)
    r = fx.iloc[0]
    # nazwa ze zrodla rozni sie od kanonicznej (wielkosc liter i spacje) -> dopasowanie rozmyte
    raw = _raw(r["home"].upper().replace("-", " "), r["away"])
    monkeypatch.setattr(daily.config, "leagues", lambda sport="football": {r["league"]: {"odds_api": "x"}})
    from typer.ingest import odds_api as oa
    monkeypatch.setattr(oa, "download", lambda *a, **k: raw)
    out = daily.snapshot_odds(tmp_engine, now=datetime(2018, 9, 8, 14, 55, tzinfo=timezone.utc))
    assert out["snapshots"] == 8
    co = db.read_df(tmp_engine, "SELECT * FROM odds_snapshots WHERE kind = 'close' AND source = 'the_odds_api'")
    assert set(co["event_id"]) == {r["event_id"]}
