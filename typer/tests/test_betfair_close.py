"""Zamkniecie Betfair z OddsRelay do CLV: zapytanie tylko przy meczu w oknie 10 min, zapis do odds_snapshots."""
from datetime import datetime, timedelta, timezone

from typer.ingest.adapters.oddsrelay import exchange_mid
from typer.ingest.core.records import OddsQuote
from typer.learn import settle
from typer.pipeline import daily
from typer.store import db

KO = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)


class FakeAdapter:
    def __init__(self, recs):
        self.recs, self.calls = recs, []

    def records(self, **kw):
        self.calls.append(kw)
        return self.recs


def _event(engine, eid="E0_x", home="Arsenal", away="Chelsea", ko=KO):
    db.upsert(engine, db.events, [dict(event_id=eid, sport="football", league="E0", season="2627", kickoff_utc=ko,
                                       home=home, away=away, status="scheduled", source="test")], ["event_id"])


def _q(book, sel, price, at, kind="close", home="Arsenal FC"):
    return OddsQuote(source="oddsrelay", source_key=f"{book}{sel}{at:%H%M}", available_at=at, fetched_at=at,
                     league="E0", kickoff_utc=KO, home=home, away="Chelsea", bookmaker=book, market="1X2",
                     selection=sel, price=price, kind=kind)


def test_bez_meczu_w_oknie_zero_zapytan(tmp_engine):
    _event(tmp_engine)
    fake = FakeAdapter([])
    out = daily.betfair_close(tmp_engine, now=KO - timedelta(minutes=30), adapter=fake)
    assert out["zapytania"] == 0 and fake.calls == []


def test_zamkniecie_betfair_trafia_do_clv(tmp_engine, monkeypatch, tmp_path):
    monkeypatch.setattr(daily, "LIVE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(daily, "ALERTS", tmp_path / "alerts.json", raising=False)
    _event(tmp_engine)
    at = KO - timedelta(minutes=6)
    mids = {"1": exchange_mid(2.16, 2.18), "X": exchange_mid(3.55, 3.65), "2": exchange_mid(3.7, 3.8)}
    fake = FakeAdapter([_q("betfair_exchange", s, p, at) for s, p in mids.items()]
                       + [_q("bet365", "1", 2.1, at - timedelta(hours=3), kind="taken")])
    out = daily.betfair_close(tmp_engine, now=at, adapter=fake)
    assert out["zapytania"] == 1 and out["betfair"] == 3 and out["zamkniecia"] == 3
    assert fake.calls == [dict(leagues=["E0"], mode="raw")]
    co = settle.closing_odds(tmp_engine)
    assert set(co["close_book"]) == {"betfair_exchange"} and len(co) == 3
    # drugi przebieg: mecz ma juz zamkniecie, wiec nie wydajemy tokenow
    assert daily.betfair_close(tmp_engine, now=at + timedelta(minutes=2), adapter=fake)["zapytania"] == 0
    assert len(fake.calls) == 1
