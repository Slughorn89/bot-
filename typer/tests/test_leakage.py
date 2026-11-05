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


# ---------------- sekcja 12.1 v2: kazda cecha i kazda klasa modelu ----------------
def test_podroz_w_czasie_wszystkie_cechy(synth):
    from typer.pipeline.layers import FEATURES
    cut = pd.Timestamp("2018-01-01").date()
    a = Engine(collect_features=True).run(synth)
    fut = synth.copy()
    m = fut["date"] >= cut
    fut.loc[m, ["fthg", "ftag", "hs", "hst"]] = 7
    b = Engine(collect_features=True).run(fut)
    pa = a[a["date"] < cut].set_index("event_id")[FEATURES]
    pb = b[b["date"] < cut].set_index("event_id")[FEATURES]
    pd.testing.assert_frame_equal(pa, pb)


def _evaluate_market(frame, tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path
    from typer.pipeline.backtest import to_preds
    f = frame.copy()
    f["bench_h"] = f["bench_d"] = f["bench_a"] = float("nan")
    _, mkt = to_preds(f, "test")
    csv, js = tmp_path / "m.csv", tmp_path / "m.json"
    mkt.to_csv(csv, index=False)
    root = Path(__file__).resolve().parent.parent
    p = subprocess.run([sys.executable, str(root / "tools" / "evaluate.py"), str(csv), "--json", str(js)],
                       capture_output=True, text=True)
    rep = json.loads(js.read_text())
    return p.returncode, {g["bramka"]: g["wynik"] for g in rep["bramki"]}


def test_uczciwy_model_online_przechodzi_brak_wycieku(synth, tmp_path):
    code, gates = _evaluate_market(Engine().run(synth, predict_from="2017-07-01"), tmp_path)
    assert gates["brak_wycieku"] == "OK"


def test_wyciek_w_prawdopodobienstwach_blokowany(synth, tmp_path):
    """Klasa 'oceny online' z wyciekiem (p zmieszane z wynikiem) -> bramka brak_wycieku czerwona."""
    fr = Engine().run(synth, predict_from="2017-07-01")
    y = np.select([fr.fthg > fr.ftag, fr.fthg == fr.ftag], [0, 1], 2)
    onehot = np.eye(3)[y]
    P = 0.5 * fr[["p_h", "p_d", "p_a"]].to_numpy() + 0.5 * onehot
    fr[["p_h", "p_d", "p_a"]] = P / P.sum(1, keepdims=True)
    tot = (fr.fthg + fr.ftag > 2.5).astype(float)
    fr["p_over"] = np.clip(0.5 * fr["p_over"] + 0.5 * tot, 0.01, 0.99)
    code, gates = _evaluate_market(fr, tmp_path)
    assert code == 2 and gates["brak_wycieku"] == "BLAD"


def test_wyciek_w_cechach_gbm_blokowany(synth, tmp_path):
    """Klasa ML: LightGBM z cecha = wynik meczu (roznica bramek) -> bramka brak_wycieku czerwona."""
    from typer.pipeline import layers as L
    fr = Engine(collect_features=True).run(synth)
    fr["roznica_bramek"] = fr["fthg"] - fr["ftag"]  # informacja z przyszlosci
    out = L.walk_forward(fr, ["2018-19", "2019-20"], L.gbm_fn(L.FEATURES + ["roznica_bramek"]),
                         train_from="2016-07-01")
    code, gates = _evaluate_market(out, tmp_path)
    assert code == 2 and gates["brak_wycieku"] == "BLAD"


def test_subtelny_wyciek_odciecia_lapie_test_wlasnego_wyniku(synth, monkeypatch):
    """Wyciek za maly na bramke (odciecie o dzien za pozno: model widzi wynik meczu przed jego typem).
    Bramka 0.03 go nie zlapie, dlatego istnieje test 'wynik meczu nie wplywa na jego predykcje'.
    Kontrola negatywna: z zepsutym odcieciem ten test MUSI wykryc zmiane."""
    from datetime import timedelta
    from typer.pipeline import engine as E
    monkeypatch.setattr(E, "prediction_cutoff", lambda d, mode="fduk": d + timedelta(days=1))
    i = len(synth) // 2
    alt = synth.copy()
    alt.loc[alt.index[i], ["fthg", "ftag", "hst", "ast"]] = [9, 0, 20, 0]
    a, b = E.Engine().run(synth), E.Engine().run(alt)
    eid = synth.iloc[i]["event_id"]
    pa = a.set_index("event_id").loc[eid, "p_h"]
    pb = b.set_index("event_id").loc[eid, "p_h"]
    assert not np.isclose(pa, pb), "zepsute odciecie powinno zmienic wlasna predykcje meczu"
