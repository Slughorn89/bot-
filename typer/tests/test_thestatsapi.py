"""Adapter TheStatsAPI: wynik, statystyki, zdarzenia z minutami (rozne odwrocone na druzyne wykonujaca),
sklady, kursy (last_seen = zamkniecie, opening = tylko benchmark), limity z naglowkow, brak klucza."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from typer.ingest.adapters.thestatsapi import TheStatsAPI
from typer.ingest.core.adapter import RawPayload

S = Path(__file__).parent / "fixtures" / "samples"
FETCHED = datetime(2026, 10, 18, 8, tzinfo=timezone.utc)


def _recs():
    return TheStatsAPI().parse(RawPayload("m.json", (S / "thestatsapi_match.json").read_bytes(), FETCHED,
                                          dict(league="E0")))


def _of(recs, name):
    return [r for r in recs if type(r).__name__ == name]


def test_wynik_statystyki_i_available_at():
    recs = _recs()
    res = _of(recs, "MatchResult")[0]
    assert (res.fthg, res.ftag, res.hthg, res.htag) == (2, 1, 1, 0)
    st = {r.side: r for r in _of(recs, "TeamMatchStats")}
    assert st["home"].xg == 1.9 and st["away"].corners == 1 and st["home"].possession_pct == 58
    for r in recs:
        assert r.available_at <= r.fetched_at


def test_rozne_odwrocone_zgodne_ze_statystykami():
    recs = _recs()
    ev = _of(recs, "MatchEvent")
    corners = [e for e in ev if e.type == "corner"]
    assert sorted((e.minute, e.team) for e in corners) == [(8, "Arsenal"), (33, "Chelsea"), (61, "Arsenal")]
    st = {r.team: r.corners for r in _of(recs, "TeamMatchStats")}
    assert {t: sum(e.team == t for e in corners) for t in st} == st
    goals = [(e.minute, e.extra_minute, e.team) for e in ev if e.type == "goal"]
    assert goals == [(20, None, "Arsenal"), (70, None, "Chelsea"), (90, 3, "Arsenal")]
    assert not any(e.type == "foul" for e in ev)                    # faule pomijane


def test_kursy_zamkniecie_i_benchmark_nigdy_wziety():
    q = _of(_recs(), "OddsQuote")
    assert {r.kind for r in q} == {"close", "bench"}
    close = {(r.market, r.selection): r.price for r in q if r.kind == "close"}
    assert close[("1X2", "1")] == 2.0 and close[("CORNERS10.5", "over10.5")] == 1.95
    assert ("CORNERS10.5", "over10.5") not in {(r.market, r.selection) for r in q if r.kind == "bench"}  # opening null
    assert all(r.bookmaker == "pinnacle" and r.available_at <= r.kickoff_utc for r in q)


def test_sklady():
    lu = _of(_recs(), "LineupEntry")
    assert {(r.team, r.status) for r in lu} == {("Arsenal", "start"), ("Arsenal", "lawka"), ("Chelsea", "start")}
    assert all(r.available_at_estimated for r in lu)


def test_mecz_nierozegrany_nic_nie_daje():
    b = json.loads((S / "thestatsapi_match.json").read_text())
    b["match"]["status"] = "scheduled"
    assert TheStatsAPI().parse(RawPayload("m.json", json.dumps(b).encode(), FETCHED, dict(league="E0"))) == []


def test_limit_miesieczny_z_naglowkow(monkeypatch, tmp_path):
    from typer.ingest import thestatsapi as api
    from typer.ingest.budget import Ledger

    def fake_fetch(url, source, name, *, params=None, headers=None, max_age_hours=None, meta=None, **kw):
        assert headers["Authorization"] == "Bearer k"
        meta.update(cache=False, headers={"X-Monthly-Quota-Limit": "50000", "X-Monthly-Quota-Remaining": "49000"})
        return json.dumps({"data": [], "meta": {"total_pages": 1}}).encode()

    monkeypatch.setattr(api, "fetch", fake_fetch)
    monkeypatch.setenv("THESTATSAPI_KEY", "k")
    led = Ledger(tmp_path / "b.json")
    api.matches("comp_3039", "sn_1", ledger=led)
    assert led.used("thestatsapi", datetime.now(timezone.utc)) == 1000


def test_brak_klucza(monkeypatch):
    from typer.ingest import thestatsapi as api
    from typer.ingest.base import SourceUnavailable
    monkeypatch.delenv("THESTATSAPI_KEY", raising=False)
    with pytest.raises(SourceUnavailable, match="THESTATSAPI_KEY"):
        api.matches("comp_3039")
