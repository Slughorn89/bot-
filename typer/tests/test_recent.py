"""Swieze mecze po koncu przypietej kopii xgabora (cykl dzienny) i terminarz Ekstraklasy.

Bez tego model na zywo nie widzial meczow od 2026-09-03, settle nie dostawal wynikow,
a cli.py history pokazywal "brak meczow". Testy bez sieci: pobieranie podmienione.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from typer.ingest import footballdata_uk as fd
from typer.ingest import schema
from typer.ingest.base import SourceUnavailable
from typer.pipeline import data

FIX = Path(__file__).parent / "fixtures"


def _rows(league, dates, pairs, source, **cols):
    out = pd.DataFrame({c: pd.Series([np.nan] * len(dates), dtype="float64") for c in schema.COLUMNS})
    out["league"], out["sport"], out["source"], out["season"] = league, "football", source, "2026-27"
    out["date"] = [pd.Timestamp(d).date() for d in dates]
    out["kickoff_utc"] = [pd.Timestamp(d + " 15:00", tz="UTC") for d in dates]
    out["time_known"] = True
    out["home"], out["away"] = [p[0] for p in pairs], [p[1] for p in pairs]
    out["fthg"], out["ftag"] = 1.0, 0.0
    for k, v in cols.items():
        out[k] = v
    out["event_id"] = [schema.make_event_id(league, d, h, a) for d, (h, a) in zip(dates, pairs)]
    return out


def test_doklejone_tylko_mecze_po_koncu_bazy(monkeypatch):
    base = pd.concat([_rows("E0", ["2026-08-30", "2026-08-31"], [("A", "B"), ("C", "D")], "xgabora", odds_h=2.0),
                      _rows("POL", ["2024-10-06"], [("Legia", "Lech")], "xgabora", bench_h=2.5)])
    new = pd.concat([_rows("E0", ["2026-08-31", "2026-10-01"], [("C", "D"), ("B", "A")], "football_data_uk",
                           odds_h=3.0),
                     _rows("POL", ["2024-10-06", "2026-11-02"], [("Legia", "Lech"), ("Lech", "Legia")],
                           "football_data_uk", close_h=1.9, close_d=3.4, close_a=4.0)])
    seen = {}

    def fake_load(seasons, leagues=None, max_age_hours=24, extended=False):
        seen.update(seasons=seasons, age=max_age_hours)
        return new.reset_index(drop=True)

    monkeypatch.setattr(fd, "load", fake_load)
    out = data.add_recent(base.reset_index(drop=True), refresh=True, today=pd.Timestamp("2026-11-08").date())
    assert seen["seasons"] == ["2026-27"] and seen["age"] == 1  # refresh = swieze pliki
    assert len(out) == 5 and out["event_id"].is_unique
    # mecz z bazy zostaje z bazy (bez podwojenia), nowy dochodzi z football-data
    assert out.loc[out["event_id"] == "E0-20260831-c-d", "odds_h"].item() == 2.0
    assert out.loc[out["event_id"] == "E0-20261001-b-a", "source"].item() == "football_data_uk"
    pol = out[out["event_id"] == "POL-20261102-lech-legia"].iloc[0]
    assert np.isnan(pol["odds_h"]) and pol["bench_h"] == 1.9  # POL: kurs tylko jako benchmark
    assert data.freshness(out, today=pd.Timestamp("2026-11-08").date())["E0"] == ("2026-10-01", 38)


def test_bez_sieci_zostaje_baza(monkeypatch):
    base = _rows("E0", ["2026-08-30"], [("A", "B")], "xgabora")

    def boom(*a, **k):
        raise SourceUnavailable("football-data.co.uk: timeout")

    monkeypatch.setattr(fd, "load", boom)
    assert data.add_recent(base).equals(base)


def test_terminarz_ekstraklasy(monkeypatch):
    main = (FIX / "fduk_E0_sample.csv").read_text(encoding="utf-8").splitlines()
    fixtures = "\n".join([main[0]] + [ln for ln in main[1:3]]).encode()
    new = ("Country,League,Date,Time,Home,Away,PSH,PSD,PSA,B365H,B365D,B365A\n"
           "Poland,Ekstraklasa,06/11/2026,17:00,Motor Lublin,Wisla Plock,,,,1.9,3.6,3.5\n"
           "Argentina,Liga Profesional,06/11/2026,18:00,Barracas Central,Racing Club,,,,2.5,3.1,3\n").encode()
    monkeypatch.setattr(fd, "fetch", lambda url, src, name, **k: new if "new_league" in url else fixtures)
    fx = fd.load_fixtures()
    assert set(fx["league"]) == {"E0", "POL"}
    pol = fx[fx["league"] == "POL"].iloc[0]
    assert pol["home"] == "Motor Lublin" and pd.isna(pol["fthg"]) and pol["event_id"].startswith("POL-20261106")


def test_historia_bez_typow_pokazuje_mecze():
    from typer.report import render
    games = [dict(data="2026-11-01", league="E0", home="Liverpool", away="Arsenal", fthg=0, ftag=1,
                  p1=0.45, px=0.27, p2=0.28, faworyt="1", trafiony=0)]
    msgs = render.render_history(dict(od="2026-10-18", do="2026-11-07", typy=[], mecze=1, lista=games, prog=0.05))
    assert "Liverpool - Arsenal 0:1 | 1 45% ❌" in msgs[0] and "wygrał w 0 z 1" in msgs[0]
    empty = render.render_history(dict(od="2026-10-18", do="2026-11-07", typy=[], mecze=0, lista=[]))
    assert "Brak rozegranych meczów" in empty[0]


def test_wzgledna_baza_sqlite_od_katalogu_typera(monkeypatch, tmp_path):
    """sqlite:///data/typer.db z .env.example nie zalezy od katalogu, z ktorego uruchomiono cli.py."""
    from typer import config
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///data/typer.db")
    assert config.database_url() == f"sqlite:///{(config.ROOT / 'data' / 'typer.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path.as_posix()}/x.db")
    assert config.database_url() == f"sqlite:///{tmp_path.as_posix()}/x.db"
