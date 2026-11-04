"""Kontrakt danych: schemat, duplikaty, strefy czasu, mapowanie nazw, bledy zrodla."""
from pathlib import Path

import pandas as pd
import pytest

from typer.entities.mapping import resolve, resolve_many
from typer.ingest import footballdata_uk, schema
from typer.ingest.xgabora import swap_day_month

FIX = Path(__file__).parent / "fixtures"


def test_syntetyk_przechodzi_kontrakt(synth):
    schema.validate(synth)


def test_duplikat_odrzucony(synth):
    bad = pd.concat([synth, synth.iloc[[5]]], ignore_index=True)
    with pytest.raises(schema.ContractError):
        schema.validate(bad)


def test_strefa_czasu_wymagana(synth):
    bad = synth.copy()
    bad["kickoff_utc"] = pd.to_datetime(bad["kickoff_utc"]).dt.tz_localize(None)
    with pytest.raises(schema.ContractError):
        schema.validate(bad)


def test_druzyna_dwa_razy_w_ciagu_doby_odrzucona(synth):
    bad = synth.copy()
    i = bad.index[10]
    other = bad[(bad["home"] == bad.at[i, "home"]) & (bad.index != i)].index[0]
    bad.loc[other, "kickoff_utc"] = bad.at[i, "kickoff_utc"] + pd.Timedelta(hours=20)
    bad.loc[other, "date"] = bad.loc[other, "kickoff_utc"].date()
    with pytest.raises(schema.ContractError, match="36 h"):
        schema.validate(bad)


def test_bledne_kursy_zerowane_i_zglaszane():
    df = pd.DataFrame({"odds_h": [2.0, 1.0, 2.0], "odds_d": [3.4, 3.0, 3.5], "odds_a": [4.0, 4.0, 0.0]})
    out, rep = schema.clean_odds(df)
    assert rep["odds_1x2"] == 2
    assert out["odds_h"].notna().sum() == 1


def test_naprawa_zamienionych_dat():
    d = pd.Series(pd.to_datetime(["2012-02-09", "2012-09-15", "2013-05-08"]))
    fixed = swap_day_month(d)
    assert list(fixed.dt.strftime("%Y-%m-%d")) == ["2012-09-02", "2012-09-15", "2013-08-05"]


def test_parser_football_data_uk_na_probce():
    """Probka w formacie football-data.co.uk (fikcyjne wartosci testowe)."""
    raw = (FIX / "fduk_E0_sample.csv").read_bytes()
    df = footballdata_uk.parse(raw, "E0", kind="main")
    assert len(df) == 3
    assert str(pd.to_datetime(df["kickoff_utc"]).dt.tz) == "UTC"
    r = df.iloc[0]
    assert r["home"] == "Man United" and r["fthg"] == 1
    # kurs wziety = Bet365, zamkniecie = Pinnacle
    assert r["odds_h"] == 1.62 and r["close_h"] == 1.60 and r["close_o25"] == 1.95
    # 20:00 czasu brytyjskiego w sierpniu (BST) = 19:00 UTC
    assert pd.Timestamp(r["kickoff_utc"]).hour == 19


def test_mapowanie_nazw():
    cands = ["Man United", "Man City", "Wolves", "Tottenham", "Nott'm Forest", "Newcastle"]
    assert resolve("Manchester United", cands).canonical == "Man United"
    assert resolve("Wolverhampton Wanderers", cands).status == "alias"
    assert resolve("Newcastle", cands).status == "auto"
    # niepewne NIE przechodzi po cichu
    assert resolve("Manchester", cands).status == "pending"
    assert resolve("Zupelnie Inna Druzyna", cands).status == "pending"
    mapping, pending = resolve_many(["Manchester United", "Man Utd", "Spurs", "Xyz FC"], cands)
    assert mapping["Spurs"] == "Tottenham"
    assert any(p.raw == "Xyz FC" for p in pending)


def test_kazda_druzyna_zmapowana_w_terminarzu():
    """Kazda nazwa z innego zrodla albo ma mapowanie, albo czeka w kolejce: nic nie ginie."""
    cands = ["Man United", "Man City", "Liverpool", "Arsenal"]
    raws = ["Manchester City", "Liverpool", "Arsenal FC", "Chelsea"]
    mapping, pending = resolve_many(raws, cands)
    assert set(mapping) | {p.raw for p in pending} == set(raws)
