"""Podroz w czasie i potasowane etykiety (sekcja 12): ochrona przed wyciekiem danych."""
import numpy as np
import pandas as pd

from typer.pipeline.engine import Engine
from typer.pipeline.layers import metrics

FEAT = ["lam_h", "lam_a", "p_h", "p_d", "p_a", "p_over", "p_btts", "atk_h", "obr_a", "elo_diff",
        "h_gf_ewm", "a_xga_ewm", "rest_h", "base_h"]


def test_podroz_w_czasie_przyszlosc_nie_zmienia_przeszlosci(synth):
    cut = pd.Timestamp("2018-01-01").date()
    a = Engine(collect_features=True).run(synth)
    fut = synth.copy()
    m = fut["date"] >= cut
    rng = np.random.default_rng(5)
    fut.loc[m, "fthg"] = rng.integers(0, 6, m.sum())
    fut.loc[m, "ftag"] = rng.integers(0, 6, m.sum())
    fut.loc[m, "hst"] = rng.integers(0, 12, m.sum())
    b = Engine(collect_features=True).run(fut)
    pa = a[a["date"] < cut].set_index("event_id")[FEAT]
    pb = b[b["date"] < cut].set_index("event_id")[FEAT]
    pd.testing.assert_frame_equal(pa, pb)
    # a pozniejsze predykcje faktycznie sie zmienily (test nie jest pusty)
    assert not np.allclose(a[a["date"] > cut]["p_h"], b[b["date"] > cut]["p_h"])


def test_wynik_meczu_nie_wplywa_na_jego_predykcje(synth):
    a = Engine().run(synth)
    i = len(synth) // 2
    alt = synth.copy()
    alt.loc[alt.index[i], ["fthg", "ftag", "hst", "ast"]] = [9, 0, 20, 0]
    b = Engine().run(alt)
    eid = synth.iloc[i]["event_id"]
    ra, rb = a.set_index("event_id").loc[eid], b.set_index("event_id").loc[eid]
    assert np.allclose(ra[FEAT].astype(float), rb[FEAT].astype(float))


def test_potasowane_etykiety_nie_bija_baseline(synth):
    """Model na losowo potasowanych wynikach musi wypasc jak baseline. Lepiej = wyciek."""
    rng = np.random.default_rng(11)
    sh = synth.copy()
    perm = rng.permutation(len(sh))
    for c in ("fthg", "ftag", "hs", "as_", "hst", "ast"):
        sh[c] = sh[c].to_numpy()[perm]
    res = Engine().run(sh, predict_from="2017-07-01")
    y = np.select([res.fthg > res.ftag, res.fthg == res.ftag], [0, 1], 2)
    ll_model = metrics(res)["ll_1x2"]
    B = res[["base_h", "base_d", "base_a"]].to_numpy()
    ll_base = -np.log(B[np.arange(len(y)), y]).mean()
    assert ll_model >= ll_base - 0.005, (ll_model, ll_base)


def test_model_uczy_sie_na_prawdziwym_sygnale(synth):
    """Kontrola testu powyzej: na nietasowanych danych model wyraznie bije baseline."""
    res = Engine().run(synth, predict_from="2017-07-01")
    y = np.select([res.fthg > res.ftag, res.fthg == res.ftag], [0, 1], 2)
    B = res[["base_h", "base_d", "base_a"]].to_numpy()
    assert metrics(res)["ll_1x2"] < -np.log(B[np.arange(len(y)), y]).mean() - 0.02


def test_odciecie_fduk_nie_uzywa_wynikow_z_dnia_zebrania_kursow():
    from datetime import date
    from typer.features.asof import prediction_cutoff
    assert prediction_cutoff(date(2024, 8, 18)) == date(2024, 8, 16)  # nd -> pt
    assert prediction_cutoff(date(2024, 8, 19)) == date(2024, 8, 16)  # pn -> pt
    assert prediction_cutoff(date(2024, 8, 21)) == date(2024, 8, 20)  # sr -> wt
    assert prediction_cutoff(date(2024, 8, 21), "day") == date(2024, 8, 21)
