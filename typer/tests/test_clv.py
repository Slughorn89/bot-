"""CLV zapisanych typow: parser zamkniec OddsRelay, mapowanie na mecze, Betfair vs bukmacherzy (bez sieci)."""
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from typer.ingest import oddsrelay_closing as orc
from typer.ingest.base import SourceUnavailable
from typer.learn import clv
from typer.store import db

FIX = Path(__file__).parent / "fixtures" / "oddsrelay_closing_sample.json"
KO = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)
EID = "E0_2026-10-18_Arsenal_Chelsea"


def test_parser_zamkniec():
    df = orc.parse(FIX.read_bytes())
    assert set(df["market"]) == {"1X2", "OU2.5"}  # btts nieznany = pominiety
    b365 = df[(df["bookmaker"] == "bet365") & (df["market"] == "1X2")].set_index("selection")["price"]
    assert b365.to_dict() == {"1": 2.00, "X": 3.50, "2": 3.80}
    assert set(df.loc[df["market"] == "OU2.5", "selection"]) == {"over2.5", "under2.5"}
    assert (df["kind"] == "close").all()


def test_paginacja_i_archiwum():
    pages = [({"data": [{"id": 1}], "meta": {"next_cursor": "c2"}}, {"cost": 1}),
             ({"data": [{"id": 2}], "meta": {"next_cursor": None}}, {"cost": 1})]
    calls = []

    def req(path, params):
        calls.append(params)
        return pages[len(calls) - 1]
    ev = orc.download_day("2026-10-18", req)
    assert [e["id"] for e in ev] == [1, 2]
    assert calls[0]["date"] == "2026-10-18" and "cursor" not in calls[0] and calls[1]["cursor"] == "c2"
    assert calls[0]["region"] == "uk"
    with pytest.raises(SourceUnavailable):
        orc.download_day("2026-10-16", req)


def _setup(engine, odds_taken=2.10, market="1X2", selection="1"):
    db.upsert(engine, db.events, [dict(event_id=EID, sport="football", league="E0", season="2627",
                                       kickoff_utc=KO, home="Arsenal", away="Chelsea", status="finished",
                                       source="test")], ["event_id"])
    with engine.begin() as c:
        pid = c.execute(db.predictions.insert().values(
            event_id=EID, market=market, selection=selection, p_model=0.52, model_version="v1",
            role="champion", odds_taken=odds_taken, predicted_utc=KO, kickoff_utc=KO)).inserted_primary_key[0]
        c.execute(db.bets.insert().values(prediction_id=pid, event_id=EID, market=market, selection=selection,
                                          odds=odds_taken, edge=0.05, stake_frac=0.01, paper=True,
                                          placed_utc=KO))


def _betfair(engine, prices):
    ts = datetime(2026, 10, 18, 13, 55, tzinfo=timezone.utc)
    db.upsert(engine, db.odds_snapshots,
              [dict(event_id=EID, source="oddsrelay", bookmaker="betfair_exchange", market="1X2", selection=s,
                    price=p, kind="close", snapshot_utc=ts) for s, p in prices.items()],
              ["event_id", "source", "bookmaker", "market", "selection", "snapshot_utc"], update=False)


def test_zamkniecia_bukmacherow_do_bazy_i_clv(tmp_engine):
    _setup(tmp_engine)
    out = clv.store_closing(tmp_engine, orc.parse(FIX.read_bytes()))
    assert out["events"] == 1 and out["unmatched"] == 0  # "Arsenal FC" -> "Arsenal"
    t = clv.tips_clv(tmp_engine)
    assert len(t) == 1 and t.loc[0, "benchmark"] == "bukmacherzy"
    # konsensus: de-vig per bukmacher, mediana, normalizacja
    p1 = [1 / 2.00 / (1 / 2.00 + 1 / 3.50 + 1 / 3.80), 1 / 1.95 / (1 / 1.95 + 1 / 3.60 + 1 / 3.90)]
    pX = [1 / 3.50 / (1 / 2.00 + 1 / 3.50 + 1 / 3.80), 1 / 3.60 / (1 / 1.95 + 1 / 3.60 + 1 / 3.90)]
    p2 = [1 / 3.80 / (1 / 2.00 + 1 / 3.50 + 1 / 3.80), 1 / 3.90 / (1 / 1.95 + 1 / 3.60 + 1 / 3.90)]
    med = np.array([np.median(p1), np.median(pX), np.median(p2)])
    fair = 1 / (med[0] / med.sum())
    assert t.loc[0, "clv"] == pytest.approx(2.10 / fair - 1)
    assert t.loc[0, "n_books"] == 2
    assert np.isnan(t.loc[0, "clv_betfair"])


def test_betfair_ma_pierwszenstwo(tmp_engine):
    _setup(tmp_engine)
    clv.store_closing(tmp_engine, orc.parse(FIX.read_bytes()))
    _betfair(tmp_engine, {"1": 2.02, "X": 3.55, "2": 4.0})
    t = clv.tips_clv(tmp_engine)
    inv = np.array([1 / 2.02, 1 / 3.55, 1 / 4.0])
    assert t.loc[0, "benchmark"] == "betfair"
    assert t.loc[0, "clv"] == pytest.approx(2.10 * inv[0] / inv.sum() - 1)
    assert t.loc[0, "clv_books"] == t.loc[0, "clv_books"]  # oba policzone
    assert t.loc[0, "close_betfair"] == 2.02


def test_niepelny_rynek_bez_clv(tmp_engine):
    _setup(tmp_engine)
    _betfair(tmp_engine, {"1": 2.02, "X": 3.55})  # brak selekcji "2": de-vig bez sensu
    t = clv.tips_clv(tmp_engine)
    assert t["clv"].isna().all()
    text, s, _ = clv.report(tmp_engine)
    assert s["z_clv"] == 0 and "brak kursów zamknięcia" in text


def test_raport(tmp_engine, tmp_path):
    _setup(tmp_engine, odds_taken=2.10)
    _betfair(tmp_engine, {"1": 2.0, "X": 3.6, "2": 4.0})
    text, s, t = clv.report(tmp_engine, csv_path=tmp_path / "clv.csv")
    assert s["z_clv"] == 1 and s["bije_zamkniecie"] == 1.0
    assert s["wg_benchmarku"] == {"betfair": 1}
    assert "CLV śr." in text and "za mało" in text
    assert (tmp_path / "clv.csv").exists()
    # filtr dat wycina typ
    assert clv.report(tmp_engine, since="2026-10-19")[1]["typy"] == 0


def test_dwuznaczne_dopasowanie_pomijane(tmp_engine):
    _setup(tmp_engine)
    db.upsert(tmp_engine, db.events, [dict(event_id="E0_dup", sport="football", league="E0", season="2627",
                                           kickoff_utc=KO, home="Arsenal", away="Chelsea", status="finished",
                                           source="test")], ["event_id"])
    out = clv.store_closing(tmp_engine, orc.parse(FIX.read_bytes()))
    assert out["snapshots"] == 0 and out["unmatched"] == 1


def test_cli_clv(tmp_engine, monkeypatch, capsys, tmp_path):
    import cli
    _setup(tmp_engine)
    monkeypatch.setattr(cli, "_engine", lambda: tmp_engine)
    monkeypatch.setattr(cli.config, "ROOT", tmp_path)
    cli.main(["clv"])
    assert "Raport CLV: 1 zapisanych typów" in capsys.readouterr().out


def test_snapshot_na_zywo_zapisuje_tylko_zamkniecie_betfair(tmp_engine):
    """Wiersze w kontrakcie adaptera typer/ingest/oddsrelay.py (parse)."""
    _setup(tmp_engine)
    snap_ts = pd.Timestamp("2026-10-18T13:55:00Z")
    base = dict(source="oddsrelay", source_event_id="r1", home_raw="Arsenal FC", away_raw="Chelsea",
                kickoff_utc=pd.Timestamp(KO), market="1X2", line=None, snapshot_utc=snap_ts,
                minutes_to_kickoff=5.0, kind="close")
    rows = [dict(base, bookmaker="betfair_exchange", is_exchange=True, selection=s, price=p, lay_price=p + 0.02)
            for s, p in (("1", 2.02), ("X", 3.55), ("2", 4.0))]
    rows += [dict(base, bookmaker="bet365", is_exchange=False, selection="1", price=1.9, lay_price=float("nan"))]
    rows += [dict(base, bookmaker="betfair_exchange", is_exchange=True, selection="1", price=2.2,
                  lay_price=2.3, kind="taken", snapshot_utc=pd.Timestamp("2026-10-18T12:00:00Z"))]
    out = clv.store_live_close(tmp_engine, pd.DataFrame(rows))
    assert out["snapshots"] == 3
    sn = db.read_df(tmp_engine, "SELECT bookmaker, source, kind FROM odds_snapshots")
    assert set(sn["bookmaker"]) == {"betfair_exchange"} and set(sn["source"]) == {"oddsrelay"}
    t = clv.tips_clv(tmp_engine)
    assert t.loc[0, "benchmark"] == "betfair" and t.loc[0, "close_betfair"] == 2.02
