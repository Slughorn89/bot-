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


def test_polish_l_with_stroke_is_not_dropped():
    from typer.entities.mapping import resolve
    assert resolve("ŁKS Łódź", ["LKS Lodz", "Widzew Lodz"]).canonical == "LKS Lodz"
    assert resolve("Jagiellonia Białystok", ["Jagiellonia", "Legia"]).canonical == "Jagiellonia"


def _match(mid, ko, home="Arsenal", away="Chelsea"):
    return dict(id=mid, utc_date=ko, home_team=dict(id="h", name=home), away_team=dict(id="a", name=away),
                status="finished", score=dict(home=1, away=0), competition_id="comp_3039")


def _stats(xh, xa):
    return {"stats": {"overview": {"expected_goals": {"all": {"home": xh, "away": xa}}}}}


def test_refresh_skips_known_and_too_fresh(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone

    from typer import config
    from typer.features import real_xg
    from typer.ingest import thestatsapi as api
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    now = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
    ms = [_match("m1", "2026-11-20T15:00:00Z"), _match("m2", "2026-11-22T10:00:00Z", "Leeds", "Fulham")]
    calls = []
    monkeypatch.setattr(api, "matches", lambda *a, **k: ms)

    def bundle(mid, parts, ledger=None, max_age_hours=None):
        calls.append((mid, parts, max_age_hours))
        return json.dumps(dict(match_id=mid, **_stats(1.7, 0.4))).encode()
    monkeypatch.setattr(api, "match_bundle", bundle)
    r = real_xg.refresh("E0", 7, now=now)
    assert r["zapytane"] == 1 and r["z_xg"] == 1          # m2 za swiezy (< 6 h po starcie)
    assert calls == [("m1", ("/stats",), 12)]
    calls.clear()
    assert real_xg.refresh("E0", 7, now=now)["zapytane"] == 0   # m1 ma juz xG: bez zapytania
    xg = real_xg.load_cached("E0")
    assert float(xg["xg_h"].iloc[0]) == 1.7 and float(xg["xg_a"].iloc[0]) == 0.4


def test_refresh_retries_match_without_xg(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone

    from typer import config
    from typer.features import real_xg
    from typer.ingest import thestatsapi as api
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    now = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(api, "matches", lambda *a, **k: [_match("m1", "2026-11-20T15:00:00Z")])
    vals = iter([(None, None), (2.0, 1.1)])

    def bundle(mid, parts, ledger=None, max_age_hours=None):
        return json.dumps(dict(match_id=mid, **_stats(*next(vals)))).encode()
    monkeypatch.setattr(api, "match_bundle", bundle)
    assert real_xg.refresh("E0", 7, now=now)["z_xg"] == 0
    assert real_xg.refresh("E0", 7, now=now)["z_xg"] == 1      # zrodlo uzupelnilo xG: drugie podejscie
    xg = real_xg.load_cached("E0")
    assert len(xg) == 1 and float(xg["xg_h"].iloc[0]) == 2.0
