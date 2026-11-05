"""Laczenie xgabora z football-data / lustrem: kontrola zgodnosci, doklejanie zamkniec, nowe mecze."""
import numpy as np
import pandas as pd
import pytest

from typer.ingest import merge, schema


def _frame(n=400, start="2024-08-10", league="E0", shift_days=0):
    rng = np.random.default_rng(0)
    d0 = pd.Timestamp(start) + pd.Timedelta(days=shift_days)
    rows = []
    for i in range(n):
        d = (d0 + pd.Timedelta(days=i)).date()
        h, a = f"T{i % 20}", f"T{(i + 7) % 20}"
        r = {c: np.nan for c in schema.COLUMNS}
        r.update(event_id=schema.make_event_id(league, d, h, a), sport="football", league=league,
                 season="2024-25", kickoff_utc=pd.Timestamp(d).tz_localize("UTC") + pd.Timedelta(hours=15),
                 time_known=True, date=d, home=h, away=a, source="test",
                 fthg=int(rng.integers(0, 4)), ftag=int(rng.integers(0, 3)),
                 odds_h=2.0, odds_d=3.4, odds_a=4.0, max_h=2.1, max_d=3.6, max_a=4.3,
                 odds_o25=1.9, odds_u25=1.95)
        rows.append(r)
    return pd.DataFrame(rows)[schema.COLUMNS]


def test_zgodne_lustro_dokleja_zamkniecia_i_nowe_mecze():
    base = _frame(400)
    other = _frame(450).assign(close_h=1.9, close_d=3.5, close_a=4.4, close_o25=1.85, close_u25=2.0,
                               odds_h=2.05)
    out, rep = merge.enrich(base, other)
    assert rep["wspolne"] == 400 and rep["nowe_mecze"] == 50
    assert out["close_h"].notna().all()
    # kurs wziety ujednolicony do zrodla football-data (Bet365)
    assert (out["odds_h"] == 2.05).all()
    assert out["event_id"].is_unique


def test_niezgodne_wyniki_odrzucaja_lustro():
    base = _frame(400)
    other = base.copy()
    other.loc[:10, "fthg"] = other.loc[:10, "fthg"] + 1   # 11/400 = 2,75% rozbieznych wynikow
    with pytest.raises(schema.ContractError):
        merge.enrich(base, other)


def test_niezgodne_kursy_odrzucaja_lustro():
    base = _frame(400)
    other = base.assign(max_h=base["max_h"] * 1.2)
    with pytest.raises(schema.ContractError):
        merge.enrich(base, other)


def test_za_male_pokrycie_odrzuca_lustro():
    base = _frame(400)
    other = _frame(400, shift_days=1000)   # zero wspolnych meczow
    with pytest.raises(schema.ContractError):
        merge.enrich(base, other)
