"""Adapter OddsRelay: snapshot w chwili typu, zamkniecia (bukmacher i gielda), odrzucanie cen z trakcie meczu,
koszt w tokenach przed zapytaniem, budzet z naglowka x-tokens-remaining, brak klucza."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from typer.ingest.adapters.oddsrelay import OddsRelay, exchange_mid
from typer.ingest.core.adapter import RawPayload

S = Path(__file__).parent / "fixtures" / "samples"


def _parse(name, fetched):
    a = OddsRelay()
    return a, a.parse(RawPayload(name, (S / name).read_bytes(), datetime.fromisoformat(fetched), dict(league="E0")))


def test_snapshot_typu_pomija_mecz_trwajacy_i_inne_rynki():
    _, recs = _parse("oddsrelay_raw.json", "2026-10-16T12:00:00+00:00")
    assert {r.home for r in recs} == {"Arsenal"}                  # Everton gra od 11:30: pominiety
    sel = {(r.market, r.selection): r.price for r in recs}
    assert sel == {("1X2", "1"): 2.2, ("1X2", "X"): 3.5, ("1X2", "2"): 3.3, ("OU2.5", "over2.5"): 1.85,
                   ("OU2.5", "under2.5"): 1.95}
    assert all(r.kind == "taken" and r.available_at == r.fetched_at for r in recs)


def test_zamkniecie_gieldy_srodek_i_cena_po_starcie_odrzucona():
    a, recs = _parse("oddsrelay_closing.json", "2026-10-17T06:00:00+00:00")
    assert all(r.kind == "close" and r.available_at <= r.kickoff_utc for r in recs)
    b365 = {r.selection: r.price for r in recs if r.bookmaker == "bet365"}
    assert b365 == {"1": 2.1, "X": 3.6}                           # Chelsea z ceny po starcie (19:50) odpada
    assert a.skipped == 1
    bf = {r.selection: r.price for r in recs if r.bookmaker == "betfair_exchange"}
    assert set(bf) == {"1", "X", "2"} and abs(bf["1"] - exchange_mid(2.16, 2.18)) < 1e-12
    assert 2.16 < bf["1"] < 2.18


def test_srodek_gieldy():
    assert exchange_mid(2.0, 2.0) == 2.0
    assert exchange_mid(None, 2.0) is None and exchange_mid(2.0, 1.0) is None


def test_koszt_sprawdzany_przed_zapytaniem_i_budzet(monkeypatch, tmp_path):
    from typer.ingest import oddsrelay as api
    from typer.ingest.budget import Ledger
    calls = []

    def fake_fetch(url, source, name, *, params=None, headers=None, max_age_hours=None, meta=None, **kw):
        calls.append(params.get("quote"))
        assert headers["Authorization"] == "Bearer test-key"
        if params.get("quote") == "true":
            return json.dumps({"cost": 1200, "remaining": 40000}).encode()
        if meta is not None:
            meta.update(cache=False, headers={"x-tokens-remaining": "38800"})
        return (S / "oddsrelay_raw.json").read_bytes()

    monkeypatch.setattr(api, "fetch", fake_fetch)
    monkeypatch.setenv("ODDSRELAY_KEY", "test-key")
    led = Ledger(tmp_path / "b.json")
    now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    api.raw_odds("soccer_epl", now=now, ledger=led)
    assert calls == ["true", None]                               # najpierw darmowa wycena
    assert led.used("oddsrelay", now) == 50000 - 38800
    led.data["oddsrelay"]["used"] = 44900                         # zostaje mniej niz koszt (z rezerwa 10%)
    with pytest.raises(Exception, match="budzet OddsRelay"):
        api.raw_odds("soccer_epl", now=now, ledger=led)


def test_brak_klucza(monkeypatch):
    from typer.ingest import oddsrelay as api
    from typer.ingest.base import SourceUnavailable
    monkeypatch.delenv("ODDSRELAY_KEY", raising=False)
    with pytest.raises(SourceUnavailable, match="ODDSRELAY_KEY"):
        api.raw_odds("soccer_epl")
