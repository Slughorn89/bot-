"""Modul 1: zaden adapter nie zwraca rekordu bez available_at (i bez spelnienia regul czasu).

Test przechodzi po CALYM rejestrze adapterow. Nowy adapter bez probek = test czerwony,
wiec nie da sie dodac zrodla z pominieciem tej kontroli."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from tests.samples import SAMPLES, payloads
from typer.ingest.core.adapter import Adapter, RawPayload, load_all
from typer.ingest.core.records import (MIN_AFTER_KICKOFF, BaseRecord, EventRef, OddsQuote, TeamMatchStats,
                                       WeatherRecord)

REG = load_all()
UTC = timezone.utc


def _records(name):
    a = REG[name]()
    out = []
    for p in payloads(name):
        out += a.validated(a.parse(p))
    return a, out


def test_rejestr_nie_jest_pusty_i_kazdy_adapter_ma_probki():
    assert len(REG) >= 8
    missing = set(REG) - set(SAMPLES)
    assert not missing, f"adaptery bez probek w tests/samples.py: {sorted(missing)}"


@pytest.mark.parametrize("name", sorted(REG))
def test_zaden_rekord_bez_available_at(name):
    a, recs = _records(name)
    assert recs, f"{name}: probki nie daly zadnego rekordu"
    for r in recs:
        assert isinstance(r, BaseRecord), type(r)
        d = r.model_dump()
        assert d.get("available_at") is not None, f"{name}: rekord bez available_at: {d}"
        assert r.available_at.tzinfo is not None and r.available_at.utcoffset() == timedelta(0)
        assert r.fetched_at.utcoffset() == timedelta(0)
        assert r.available_at <= r.fetched_at, f"{name}: available_at po fetched_at"
        if isinstance(r, EventRef) and r.post_match:
            assert r.available_at >= r.kickoff_utc + MIN_AFTER_KICKOFF, f"{name}: dane pomeczowe przed koncem"
        if isinstance(r, OddsQuote) and r.kind == "close":
            assert r.available_at >= r.kickoff_utc - timedelta(minutes=15)


@pytest.mark.parametrize("name", sorted(REG))
def test_kazdy_zadeklarowany_typ_rekordu_ma_pokrycie_w_probkach(name):
    a, recs = _records(name)
    got = {type(r) for r in recs}
    assert set(a.record_types) <= got, f"{name}: brak probek dla {[t.__name__ for t in set(a.record_types) - got]}"


# ---------------- kontrole negatywne: test musi umiec oblac ----------------
KO = datetime(2024, 8, 17, 14, tzinfo=UTC)
BASE = dict(source="t", source_key="k", league="E0", kickoff_utc=KO, home="A", away="B", team="A", side="home",
            fetched_at=KO + timedelta(days=1))


def test_rekord_bez_available_at_nie_powstanie():
    with pytest.raises(ValidationError, match="available_at"):
        TeamMatchStats(**BASE)


def test_naiwny_czas_bez_strefy_odrzucony():
    with pytest.raises(ValidationError):
        TeamMatchStats(**BASE, available_at=datetime(2024, 8, 17, 18))


def test_statystyki_meczu_przed_jego_koncem_odrzucone():
    with pytest.raises(ValidationError, match="wyciek"):
        TeamMatchStats(**BASE, available_at=KO + timedelta(minutes=30))


def test_available_at_po_fetched_at_odrzucone():
    with pytest.raises(ValidationError, match="fetched_at"):
        TeamMatchStats(**{**BASE, "fetched_at": KO + timedelta(hours=3)}, available_at=KO + timedelta(hours=4))


def test_obserwacja_pogody_nie_udaje_prognozy():
    w = dict(source="t", source_key="k", latitude=51.5, longitude=0.0, valid_time=KO, fetched_at=KO + timedelta(days=2))
    with pytest.raises(ValidationError, match="prognoza"):
        WeatherRecord(**w, kind="forecast", available_at=KO + timedelta(hours=1))
    with pytest.raises(ValidationError, match="obserwacja"):
        WeatherRecord(**w, kind="observed", available_at=KO - timedelta(hours=1))


def test_adapter_zwracajacy_cos_innego_niz_rekord_jest_odrzucany():
    class Zly(Adapter):
        name = "zly_testowy"

        def fetch(self, **p):
            return [RawPayload("x", b"", KO)]

        def parse(self, payload):
            return [dict(source="t", source_key="k")]  # slownik bez available_at

    with pytest.raises(TypeError, match="zamiast rekordu"):
        Zly().records()
