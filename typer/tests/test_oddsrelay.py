"""OddsRelay: klient HTTP (tokeny, bledy, strony) i parser /v2/odds/raw na atrapie, bez sieci."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import requests

from typer.ingest import oddsrelay
from typer.ingest.base import SourceUnavailable
from typer.ingest.odds_api import best_price

FIX = Path(__file__).parent / "fixtures" / "oddsrelay_raw_sample.json"
KEY = "test-key-123"
SNAP_CLOSE = datetime(2026, 11, 8, 14, 55, tzinfo=timezone.utc)  # 5 min przed startem


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}

    def json(self):
        return self._body


class FakeSession:
    """Zwraca kolejne odpowiedzi i zapisuje, z czym bylo wolane."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, headers=None, **kw):
        self.calls.append(dict(url=url, params=dict(params or {}), headers=dict(headers or {}), **kw))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def tok(remaining, cost=10, used=100):
    return {"X-Tokens-Cost": str(cost), "X-Tokens-Used": str(used), "X-Tokens-Remaining": str(remaining),
            "X-Tokens-Limit": "50000", "X-Tokens-Reset": "2026-11-19T00:00:00Z"}


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("ODDSRELAY_KEY", f"  {KEY}\n")  # spacje z pliku maja byc obciete


def events():
    return json.loads(FIX.read_text())["data"]


# --- parser ---

def test_parser_bukmacherzy_i_gielda():
    snap = oddsrelay.parse(events(), SNAP_CLOSE, leagues={"soccer_epl": "E0"})
    assert set(snap["league"]) == {"E0"}
    assert set(snap["source"]) == {"oddsrelay"}
    assert set(snap["market"]) == {"1X2"}
    assert set(snap["selection"]) == {"1", "X", "2"}
    assert (snap["kind"] == "close").all()
    assert "or_outright" not in set(snap["source_event_id"])  # zdarzenie bez druzyn pominiete
    bf = snap[snap["bookmaker"] == "betfair_exchange"].set_index("selection")
    assert bf.loc["1", "price"] == 2.16 and bf.loc["1", "lay_price"] == 2.18  # najlepszy back i lay
    assert bf["is_exchange"].all()
    sm = snap[snap["bookmaker"] == "smarkets"].iloc[0]
    assert (sm["price"], sm["lay_price"]) == (2.14, 2.20)  # back/lay jako pojedyncze liczby
    bk = snap[~snap["is_exchange"]]
    assert bk["lay_price"].isna().all() and set(bk["bookmaker"]) == {"bet365", "williamhill"}


def test_parser_kind_i_best_price():
    early = oddsrelay.parse(events(), datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc))
    assert (early["kind"] == "taken").all()
    assert set(early["league"]) == {"soccer_epl"}  # bez mapowania zostaje klucz rozgrywek
    late = oddsrelay.parse(events(), datetime(2026, 11, 8, 15, 30, tzinfo=timezone.utc))
    assert (late["kind"] == "inplay").all()
    best = best_price(early, bookmakers=["bet365", "williamhill"])
    assert best.set_index("selection").loc["2", "price"] == 3.60
    assert oddsrelay.parse([], SNAP_CLOSE).empty


# --- klient HTTP ---

def test_klucz_tylko_w_naglowku_i_tokeny(key):
    s = FakeSession(Resp(200, {"data": []}, tok(42000)))
    body, t = oddsrelay.request("/v2/odds/raw", {"region": "uk"}, session=s)
    call = s.calls[0]
    assert call["headers"]["Authorization"] == f"Bearer {KEY}"
    assert KEY not in call["url"] and KEY not in json.dumps(call["params"])
    assert call["url"] == "https://api.oddsrelay.io/v2/odds/raw" and call["allow_redirects"] is False
    assert t == dict(cost=10, used=100, remaining=42000, limit=50000, reset="2026-11-19T00:00:00Z")


def test_tokeny_unlimited_i_brak_naglowkow():
    t = oddsrelay.tokens_from_headers({"x-tokens-remaining": "unlimited"})
    assert t["remaining"] == "unlimited" and t["cost"] is None
    assert not oddsrelay.tokens_low(t)
    assert not oddsrelay.tokens_low(oddsrelay.tokens_from_headers({}))
    assert oddsrelay.tokens_low(oddsrelay.tokens_from_headers(tok(100)), threshold=5000)


def test_ostrzezenie_przy_malej_liczbie_tokenow(key, caplog):
    s = FakeSession(Resp(200, {"data": []}, tok(1200)))
    with caplog.at_level(logging.WARNING, logger="typer.ingest.oddsrelay"):
        oddsrelay.request("/v2/odds/raw", session=s)
    assert "1200" in caplog.text


def test_brak_klucza(monkeypatch):
    monkeypatch.delenv("ODDSRELAY_KEY", raising=False)
    with pytest.raises(SourceUnavailable, match="ODDSRELAY_KEY"):
        oddsrelay.request("/v2/odds/raw", session=FakeSession())


def test_402_bez_ponawiania(key):
    s = FakeSession(Resp(402, {"error": {"code": "insufficient_tokens"}}, tok(0)))
    with pytest.raises(oddsrelay.TokensExhausted, match="insufficient_tokens"):
        oddsrelay.request("/v2/odds/raw", session=s, sleep=lambda _: None)
    assert len(s.calls) == 1


@pytest.mark.parametrize("status", [400, 401, 403])
def test_bledy_trwale_bez_ponawiania(key, status):
    s = FakeSession(Resp(status, {"error": {"code": "x"}}))
    with pytest.raises(SourceUnavailable, match=str(status)):
        oddsrelay.request("/v2/odds/raw", session=s, sleep=lambda _: None)
    assert len(s.calls) == 1


def test_429_czeka_retry_after(key):
    waits = []
    s = FakeSession(Resp(429, headers={"Retry-After": "7"}), Resp(200, {"data": [1]}, tok(40000)))
    body, _ = oddsrelay.request("/v2/odds/raw", session=s, sleep=waits.append)
    assert body == {"data": [1]} and waits == [7.0]


def test_5xx_i_siec_ponawiane_potem_wyjatek(key):
    waits = []
    s = FakeSession(Resp(503), requests.ConnectionError("x"), Resp(500), Resp(502))
    with pytest.raises(SourceUnavailable, match="502"):
        oddsrelay.request("/v2/odds/raw", session=s, retries=3, sleep=waits.append)
    assert waits == [2.0, 4.0, 8.0] and len(s.calls) == 4


def test_proxy_bez_ponawiania(key):
    s = FakeSession(requests.exceptions.ProxyError("403"))
    with pytest.raises(SourceUnavailable, match="proxy"):
        oddsrelay.request("/v2/odds/raw", session=s, sleep=lambda _: None)
    assert len(s.calls) == 1


# --- pobranie snapshotu ---

def test_download_strony_parametry_i_zapis(key, tmp_path):
    ev = events()
    s = FakeSession(Resp(200, {"data": ev[:1], "meta": {"next_cursor": "c2"}}, tok(40000, cost=25)),
                    Resp(200, {"data": ev[1:], "meta": {"next_cursor": None}}, tok(39975, cost=25)))
    out, t = oddsrelay.download(SNAP_CLOSE, raw_dir=tmp_path, session=s, max_tokens=0)
    assert [e["id"] for e in out] == ["or_evt_1", "or_outright"]
    p0, p1 = s.calls[0]["params"], s.calls[1]["params"]
    assert (p0["region"], p0["sports"], p0["markets"]) == ("uk", "soccer", "h2h") and "cursor" not in p0
    assert p1["cursor"] == "c2"
    assert t["spent"] == 50 and t["remaining"] == 39975
    saved = json.loads((tmp_path / "oddsrelay" / "soccer_h2h_20261108T1455.json").read_text())
    assert len(saved["data"]) == 2
    snap = oddsrelay.parse(out, SNAP_CLOSE)
    assert len(snap) == 10  # 2 bukmacherow x 3 + Betfair x 3 + Smarkets x 1


def test_download_za_drogo_nie_pobiera(key, tmp_path):
    s = FakeSession(Resp(200, {"cost": 900, "remaining": 1000}))
    with pytest.raises(SourceUnavailable, match="900"):
        oddsrelay.download(SNAP_CLOSE, raw_dir=tmp_path, session=s, max_tokens=500)
    assert len(s.calls) == 1 and s.calls[0]["params"]["quote"] == "true"
    assert not (tmp_path / "oddsrelay").exists()
