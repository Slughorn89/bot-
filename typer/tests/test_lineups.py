"""Sklady i kontuzje: parsery API-Football (probki z dokumentacji), budzet zapytan, cecha brakow
"as of" (podroz w czasie), dopasowanie challengera z kara, zapis do bazy end to end."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from typer.features import lineups as FL
from typer.ingest import api_football as af
from typer.ingest.base import SourceUnavailable
from typer.models import lineup_adjust as LA
from typer.store import db

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 7, 14, 0, tzinfo=timezone.utc)


def _load(name):
    return json.loads((FIX / name).read_text())


# --- parsery ----------------------------------------------------------------------------------
def test_parse_fixtures_lineups_injuries():
    fx = af.parse_fixtures(_load("api_football_fixtures.json"))
    assert list(fx["fixture_id"]) == [1300101, 1300102]
    assert str(fx["kickoff_utc"].dt.tz) == "UTC" and fx.iloc[0]["home"] == "Manchester United"
    lu = af.parse_lineups(_load("api_football_lineups.json"), NOW)
    assert len(lu) == 36 and lu["is_starter"].sum() == 22
    inj = af.parse_injuries(_load("api_football_injuries.json"), NOW)
    assert set(inj["player"]) == {"MU P9", "EV P7"} and (inj["fixture_id"] == 1300101).all()


def test_niekompletny_sklad_odrzucony():
    d = _load("api_football_lineups.json")
    d["response"][0]["startXI"] = d["response"][0]["startXI"][:10]
    assert af.parse_lineups(d, NOW).empty


def test_sezon_api_football():
    assert af.season_year("2026-11-07") == 2026 and af.season_year("2027-03-01") == 2026


# --- budzet i bledy -----------------------------------------------------------------------------
@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(af, "RAW_DIR", tmp_path)
    monkeypatch.setenv("API_FOOTBALL_KEY", "test")
    return tmp_path


def test_budzet_blokuje_zapytania(raw, monkeypatch):
    calls = []
    monkeypatch.setattr(af, "fetch", lambda *a, **k: calls.append(1) or b'{"errors": [], "response": []}')
    monkeypatch.setattr(af, "_src", lambda: {"limit_dzienny": 3, "rezerwa": 1})
    af.download_lineups(1)
    af.download_lineups(2)
    with pytest.raises(SourceUnavailable, match="budzet"):
        af.download_lineups(3)
    assert len(calls) == 2 and af.budget_used() == 2


def test_pole_errors_to_niedostepne_zrodlo(raw, monkeypatch):
    monkeypatch.setattr(af, "fetch", lambda *a, **k: b'{"errors": {"token": "Error/Missing application key"}}')
    with pytest.raises(SourceUnavailable, match="token"):
        af.download_lineups(1)


def test_brak_klucza(raw, monkeypatch):
    monkeypatch.delenv("API_FOOTBALL_KEY")
    with pytest.raises(SourceUnavailable, match="API_FOOTBALL_KEY"):
        af.download_lineups(1)


# --- cecha brakow "as of" -------------------------------------------------------------------------
def _history(n_games=5, team="A"):
    """n_games meczow druzyny A, zawsze ci sami P1..P11 w podstawie, P12..P14 na lawce."""
    rows = []
    ko0 = pd.Timestamp("2026-09-01 15:00", tz="UTC")
    for g in range(n_games):
        ko = ko0 + pd.Timedelta(days=7 * g)
        for i in range(1, 15):
            rows.append(dict(event_id=f"g{g}", team=team, player=f"P{i}", is_starter=i <= 11,
                             published_utc=ko - pd.Timedelta(minutes=60), kickoff_utc=ko))
    return pd.DataFrame(rows), ko0 + pd.Timedelta(days=7 * n_games)


def _today(ko, starters, eid="today", team="A", published=None):
    return pd.DataFrame([dict(event_id=eid, team=team, player=p, is_starter=True,
                              published_utc=published or ko - pd.Timedelta(minutes=60), kickoff_utc=ko)
                         for p in starters])


AB0 = pd.DataFrame(columns=["event_id", "team", "player", "published_utc", "kickoff_utc"])


def test_braki_ze_skladu():
    hist, ko = _history()
    today = _today(ko, [f"P{i}" for i in range(3, 12)] + ["P12", "P13"])   # brak P1 i P2
    lu = pd.concat([hist, today])
    assert FL.missing_share(lu, AB0, "today", "A", ko) == pytest.approx(2 / 11)


def test_braki_podroz_w_czasie():
    """Sklad opublikowany po starcie i mecze z przyszlosci nie zmieniaja cechy."""
    hist, ko = _history()
    late = _today(ko, [f"P{i}" for i in range(5, 12)] + ["P12", "P13", "P14", "X"],
                  published=ko + pd.Timedelta(minutes=5))
    future, _ = _history(3)
    future = future.assign(event_id=lambda d: "f" + d["event_id"], player="Z",
                           kickoff_utc=lambda d: d["kickoff_utc"] + pd.Timedelta(days=200),
                           published_utc=lambda d: d["published_utc"] + pd.Timedelta(days=200))
    base = FL.missing_share(hist, AB0, "today", "A", ko)
    assert FL.missing_share(pd.concat([hist, late, future]), AB0, "today", "A", ko) == base


def test_braki_z_kontuzji_gdy_brak_skladu():
    hist, ko = _history()
    ab = pd.DataFrame([dict(event_id="today", team="A", player="P4", published_utc=ko - pd.Timedelta(hours=5),
                            kickoff_utc=ko)])
    assert FL.missing_share(hist, ab, "today", "A", ko) == pytest.approx(1 / 11)


def test_za_malo_historii_to_nan():
    hist, ko = _history(n_games=2)
    assert np.isnan(FL.missing_share(hist, AB0, "today", "A", ko))


# --- dopasowanie challengera ----------------------------------------------------------------------
def _sim(n, b, g, seed=0):
    rng = np.random.default_rng(seed)
    lh, la = rng.uniform(0.9, 2.0, n), rng.uniform(0.6, 1.5, n)
    mh, ma = rng.beta(1, 6, n), rng.beta(1, 6, n)
    th, ta = LA.adjust(lh, la, mh, ma, b, g)
    return pd.DataFrame(dict(lam_h=lh, lam_a=la, braki_h=mh, braki_a=ma,
                             fthg=rng.poisson(th), ftag=rng.poisson(ta)))


def test_fit_bez_danych_zero():
    p = LA.fit(pd.DataFrame(columns=["lam_h", "lam_a", "braki_h", "braki_a", "fthg", "ftag"]))
    assert p == dict(b=0.0, g=0.0, n=0)


def test_fit_odzyskuje_efekt_na_duzej_probie():
    p = LA.fit(_sim(20000, b=0.8, g=0.4), kara=1.0)
    assert p["b"] == pytest.approx(0.8, abs=0.15) and p["g"] == pytest.approx(0.4, abs=0.15)


def test_fit_kara_ciagnie_do_zera_na_malej_probie():
    p = LA.fit(_sim(30, b=0.8, g=0.4, seed=3))
    assert abs(p["b"]) < 0.2 and abs(p["g"]) < 0.2


def test_adjust_zero_i_nan_bez_zmian():
    lh, la = LA.adjust([1.5], [1.1], [np.nan], [0.3], 0.0, 0.0)
    assert lh[0] == 1.5 and la[0] == 1.1


# --- zapis do bazy end to end ----------------------------------------------------------------------
def test_collect_zapisuje_sklady_i_kontuzje(tmp_engine, raw, monkeypatch):
    ko = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)
    db.upsert(tmp_engine, db.events, [dict(event_id="E0-mu-eve", sport="football", league="E0", season="2026-27",
                                           kickoff_utc=ko, home="Man United", away="Everton",
                                           status="scheduled", source="test")], ["event_id"])
    monkeypatch.setattr(af, "download_fixtures", lambda lg, day: _load("api_football_fixtures.json"))
    monkeypatch.setattr(af, "download_injuries", lambda lg, day: _load("api_football_injuries.json"))
    monkeypatch.setattr(af, "download_lineups", lambda fid: _load("api_football_lineups.json"))
    from typer.pipeline import lineups
    out = lineups.collect(tmp_engine, now=ko - timedelta(minutes=60), window_min=90)
    assert out["sklady"] == 1 and out["kontuzje"] == 2, out
    lu = db.read_df(tmp_engine, "SELECT * FROM lineups")
    assert set(lu["team"]) == {"Man United", "Everton"} and lu["is_starter"].sum() == 22
    # drugie uruchomienie nie dubluje skladow (mecz juz ma sklad)
    out2 = lineups.collect(tmp_engine, now=ko - timedelta(minutes=45), window_min=90)
    assert out2["mecze"] == 0 and len(db.read_df(tmp_engine, "SELECT * FROM lineups")) == len(lu)
