"""Dolaczanie prawdziwego xG: dopasowanie nazw i dat, brak = NaN, kolejnosc wierszy zachowana."""
import datetime as dt

import numpy as np
import pandas as pd

from typer.features.real_xg import attach


def test_attach_matches_names_and_dates():
    df = pd.DataFrame(dict(league=["E0", "E0", "D1"], home=["Man United", "Arsenal", "Dortmund"],
                           away=["Arsenal", "Man United", "Bochum"],
                           date=[dt.date(2024, 9, 1), dt.date(2025, 1, 5), dt.date(2024, 9, 2)]))
    xg = {"E0": pd.DataFrame(dict(src_home=["Manchester United"], src_away=["Arsenal"],
                                  kickoff_utc=["2024-09-01T15:00:00Z"], xg_h=[1.4], xg_a=[0.7])),
          "D1": pd.DataFrame(dict(src_home=["Borussia Dortmund"], src_away=["VfL Bochum 1848"],
                                  kickoff_utc=["2024-09-02T18:30:00Z"], xg_h=[2.1], xg_a=[0.3]))}
    out, pending = attach(df, xg)
    assert list(out.index) == list(df.index)
    assert out.loc[0, "xg_h"] == 1.4 and out.loc[0, "xg_a"] == 0.7
    assert np.isnan(out.loc[1, "xg_h"])          # rewanz bez xG: silnik wraca do przyblizenia
    assert out.loc[2, "xg_h"] == 2.1 and pending == []


def test_attach_without_cache_gives_nan():
    df = pd.DataFrame(dict(league=["XX"], home=["A"], away=["B"], date=[dt.date(2024, 1, 1)]))
    out, _ = attach(df, {"XX": pd.DataFrame(columns=["src_home", "src_away", "kickoff_utc", "xg_h", "xg_a"])})
    assert out["xg_h"].isna().all()
