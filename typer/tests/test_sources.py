"""Zrodla z limitami (sekcja 5 v2): budzet zapytan, planer snapshotow, kontrakt i zapis skladow."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from typer.ingest import api_football as af
from typer.ingest import budget

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2018, 9, 8, 14, 52, tzinfo=timezone.utc)


def _events(kickoffs, league="E0"):
    return pd.DataFrame(dict(event_id=[f"e{i}" for i in range(len(kickoffs))], league=league,
                             home=[f"H{i}" for i in range(len(kickoffs))], away=[f"A{i}" for i in range(len(kickoffs))],
                             kickoff_utc=pd.to_datetime(kickoffs, utc=True)))


def test_koszt_odds_api_to_rynki_razy_regiony():
    assert budget.odds_api_cost(["h2h", "totals"], ["eu"]) == 2
    assert budget.odds_api_cost(["h2h", "totals"], ["eu", "uk"]) == 4


def test_ksiega_odmawia_ponad_budzet_i_ufa_naglowkom(tmp_path):
    led = budget.Ledger(tmp_path / "b.json")
    assert led.remaining("the_odds_api", NOW) == 450  # 500 minus 10% rezerwy
    led.record("the_odds_api", 2, NOW, {"x-requests-used": "449", "x-requests-remaining": "51"})
    assert led.used("the_odds_api", NOW) == 449
    assert led.can_spend("the_odds_api", 1, NOW) and not led.can_spend("the_odds_api", 2, NOW)
    # nowy miesiac = nowy licznik
    assert led.used("the_odds_api", datetime(2018, 10, 1, tzinfo=timezone.utc)) == 0
    # API-Football: limit dzienny z naglowka pozostalych zapytan
    led.record("api_football", 1, NOW, {"x-ratelimit-requests-remaining": "40"})
    assert led.used("api_football", NOW) == 60


def test_planer_zamkniecie_i_typ_w_oknach(tmp_path):
    led = budget.Ledger(tmp_path / "b.json")
    ev = _events(["2018-09-08 15:00", "2018-09-08 17:30"])
    plans = budget.plan_odds_snapshots(ev, NOW, set(), led)
    kinds = sorted((p.kind, p.cost) for p in plans)
    assert kinds == [("close", 2), ("taken", 2)]  # zamkniecie 15:00 + typ raz na dzien
    # po wykonaniu nic sie nie powtarza
    done = {("E0", "close", str(pd.Timestamp("2018-09-08 15:00", tz="UTC"))), ("E0", "taken", "2018-09-08")}
    assert budget.plan_odds_snapshots(ev, NOW, done, led) == []
    # za wczesnie na cokolwiek
    assert budget.plan_odds_snapshots(ev, datetime(2018, 9, 8, 9, 0, tzinfo=timezone.utc), set(), led) == []


def test_planer_przy_malym_budzecie_najpierw_zamkniecie_potem_typ_bez_totals(tmp_path):
    led = budget.Ledger(tmp_path / "b.json")
    led.record("the_odds_api", 0, NOW, {"x-requests-used": "447"})  # zostaly 3 kredyty z 450
    plans = budget.plan_odds_snapshots(_events(["2018-09-08 15:00", "2018-09-08 17:30"]), NOW, set(), led)
    assert [(p.kind, p.markets) for p in plans] == [("close", ["h2h", "totals"]), ("taken", ["h2h"])]


def test_odds_api_nie_wola_api_ponad_budzet(monkeypatch, tmp_path):
    from typer.ingest import odds_api
    from typer.ingest.base import SourceUnavailable
    monkeypatch.setenv("ODDS_API_KEY", "x")
    led = budget.Ledger(tmp_path / "b.json")
    led.record("the_odds_api", 0, NOW, {"x-requests-used": "450"})
    called = []
    monkeypatch.setattr(odds_api, "fetch", lambda *a, **k: called.append(1) or b"[]")
    with pytest.raises(SourceUnavailable, match="budzet"):
        odds_api.download("soccer_epl", now=NOW, ledger=led)
    assert not called


def test_kontrakt_skladow():
    raw = (FIX / "apifootball_lineups.json").read_bytes()
    lu = af.parse_lineups(raw)
    assert len(lu) == 4 and lu["is_starter"].sum() == 3
    assert set(lu["status"]) == {"start", "lawka"}
    broken = json.loads(raw)
    del broken["response"][0]["startXI"]
    with pytest.raises(ValueError, match="startXI"):
        af.parse_lineups(json.dumps(broken).encode())


def test_kontuzje_i_zawieszenia():
    inj = af.parse_injuries((FIX / "apifootball_injuries.json").read_bytes())
    assert dict(zip(inj["player"], inj["status"])) == {"Testowy Kontuzjowany": "nieobecny",
                                                       "Testowy Pauzujacy": "zawieszenie"}


def test_sklady_trafiaja_do_bazy_z_mapowaniem(monkeypatch, tmp_engine, synth, tmp_path):
    from typer.pipeline import daily
    from typer.store import db
    monkeypatch.setattr(daily, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(daily, "ALERTS", tmp_path / "alerts.json")
    fx = synth[synth["date"] == pd.Timestamp("2018-09-08").date()].head(1).copy()
    fx[["fthg", "ftag"]] = float("nan")
    db.store_matches(tmp_engine, fx)
    r = fx.iloc[0]
    sub = lambda name: (FIX / name).read_text(encoding="utf-8").replace("HOME_PLACEHOLDER", r["home"].upper()).replace(
        "AWAY_PLACEHOLDER", r["away"]).encode()
    files = {"/fixtures": "apifootball_fixtures.json", "/injuries": "apifootball_injuries.json",
             "/fixtures/lineups": "apifootball_lineups.json"}
    monkeypatch.setattr(af, "download", lambda path, params, **k: sub(files[path]))
    monkeypatch.setenv("API_FOOTBALL_KEY", "test")
    monkeypatch.setattr(daily.config, "sources", lambda: {"api_football": {"ligi": {r["league"]: 999}}})
    out = daily.collect_lineups(tmp_engine, now=NOW)
    assert out == {"mecze": 1, "wiersze": 6}
    lu = db.read_df(tmp_engine, "SELECT team, player, status FROM lineups")
    assert set(lu["team"]) == {r["home"], r["away"]}  # nazwy zmapowane na kanoniczne
    assert {"nieobecny", "zawieszenie", "start", "lawka"} == set(lu["status"])
    assert daily.collect_lineups(tmp_engine, now=NOW) == {"mecze": 0, "wiersze": 0}  # nie dublujemy
