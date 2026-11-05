"""Testy narzedzia ewaluacji. Uruchom: pytest -q tests/test_evaluate_v2.py"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))
import evaluate  # noqa: E402
import eval_synth as synth  # noqa: E402


def run(df, tmp_path, *args):
    csv, js = tmp_path / "p.csv", tmp_path / "r.json"
    df.to_csv(csv, index=False)
    r = subprocess.run([sys.executable, str(ROOT / "tools/evaluate.py"), str(csv), "--json", str(js), *args],
                       capture_output=True, text=True)
    rep = json.loads(js.read_text()) if js.exists() else None
    return r.returncode, rep, r.stdout + r.stderr


def gate(rep, name):
    return next((g["wynik"] for g in rep["bramki"] if g["bramka"] == name), None)


# --- werdykty: narzedzie musi odroznic uczciwy model od zepsutego -------------------------
@pytest.mark.parametrize("ou", [True, False])
def test_uczciwy_model_gotowy(tmp_path, ou):
    code, rep, _ = run(synth.make(kind="honest", ou_single=ou), tmp_path, "--value-threshold", "0.03")
    assert code == 0 and rep["gotowy_do_gry"]
    assert rep["schema"] == "typer.report/v2"


@pytest.mark.parametrize("ou", [True, False])
def test_wyciek_blokowany_takze_przy_mieszanych_rynkach(tmp_path, ou):
    # regresja: w v1 jeden rynek bez kursu zamkniecia wylaczal bramke brak_wycieku
    code, rep, _ = run(synth.make(kind="leak", ou_single=ou), tmp_path, "--value-threshold", "0.03")
    assert code == 2
    assert gate(rep, "brak_wycieku") == "BLAD"


def test_losowy_model_nie_przechodzi_baseline(tmp_path):
    code, rep, _ = run(synth.make(kind="random"), tmp_path, "--value-threshold", "0.03")
    assert code == 2 and gate(rep, "lepszy_od_baseline") == "BLAD"


def test_niespojne_prawdopodobienstwa(tmp_path):
    code, rep, _ = run(synth.make(kind="bad_sum", ou_single=False), tmp_path)
    assert code == 2 and gate(rep, "spojnosc_prawdopodobienstw") == "BLAD"


def test_mala_proba(tmp_path):
    code, rep, _ = run(synth.make(n=120, ou_single=False), tmp_path)
    assert code == 2 and gate(rep, "proba") == "BLAD"


# --- kontrakt danych: zly plik = kod 3, nigdy cichy wynik --------------------------------
@pytest.mark.parametrize("psuj", [
    lambda d: pd.concat([d, d.iloc[:3]]),                       # duplikat meczu
    lambda d: d.assign(outcome=d["outcome"].replace(1, 2)),     # outcome spoza {0,1}
    lambda d: d.assign(p_model=d["p_model"] * 3),               # p > 1
    lambda d: d.assign(odds_close=0.9),                         # kurs <= 1
    lambda d: d.drop(columns=["selection"]),                    # brak kolumny
])
def test_kontrakt_danych(tmp_path, psuj):
    code, rep, out = run(psuj(synth.make(n=400, ou_single=False)), tmp_path)
    assert code == 3 and rep is None, out


# --- dryf: zamieniony gospodarz i gosc w jednej lidze --------------------------------------
def test_dryf_wykrywa_blad_danych(tmp_path):
    # model dostaje zamienionego gospodarza i goscia w jednej lidze od polowy okresu,
    # rynek (inne zrodlo) jest poprawny: nadwyzka log loss rosnie tylko w L1
    d = synth.make(n=4000, ou_single=False, seed=3)
    ev_l1 = d[d.league == "L1"]["event_id"].unique()
    zle = d["event_id"].isin(set(ev_l1[len(ev_l1) // 2:]))
    p = d.pivot(index="event_id", columns="selection", values="p_model")
    p[["1", "2"]] = p[["2", "1"]].to_numpy()
    sw = p.stack().rename("p_sw")
    d = d.join(sw, on=["event_id", "selection"])
    d.loc[zle, "p_model"] = d.loc[zle, "p_sw"]
    _, rep, _ = run(d.drop(columns="p_sw"), tmp_path)
    assert any("L1" in k for k in rep["dryf"]), rep["dryf"]
    assert not any(("L0" in k) or ("L2" in k) for k in rep["dryf"]), rep["dryf"]


@pytest.mark.slow
def test_dryf_rzadkie_falszywe_alarmy_na_uczciwym_modelu():
    # ok. 17 tys. monitorowanych zdarzen uczciwego modelu: nowe progi musza dawac co najmniej
    # 2x mniej falszywych alarmow niz stare (k=0.1, h=22). W pomiarze: 7 vs 22.
    def licz(k, h):
        n = 0
        for seed in range(5):
            d = synth.make(n=6000, ou_single=False, seed=seed)
            d["date"] = pd.to_datetime(d["date"])
            ev, _, _ = evaluate.event_table(evaluate.add_fair_close(d))
            for _, g in ev.groupby("league"):
                n += len(evaluate.cusum_drift(g.reset_index(drop=True), k=k, h=h))
        return n
    nowe, stare = licz(None, None), licz(0.1, 22.0)
    assert nowe * 2 <= stare, (nowe, stare)


# --- jednostkowe ----------------------------------------------------------------------------
def test_devig_proporcjonalny():
    d = pd.DataFrame(dict(event_id=["a"] * 3, market=["1X2"] * 3, odds_close=[2.0, 3.4, 4.0]))
    fair = evaluate.add_fair_close(d)["odds_close_fair"].to_numpy()
    assert np.isclose((1 / fair).sum(), 1.0)
    assert np.all(fair > d["odds_close"].to_numpy())  # zdjeta marza = wyzsze kursy fair


def test_jeden_zaklad_na_mecz_przy_value_threshold():
    d = synth.make(n=500, ou_single=False)
    d["date"] = pd.to_datetime(d["date"])
    b = evaluate.select_bets(d, 0.0)
    assert b["event_id"].is_unique


def test_bootstrap_porcjami_stabilny():
    x = np.random.default_rng(0).normal(0.02, 0.1, 5000)
    lo, hi = evaluate.boot(lambda a: a.mean(1), [x])
    assert lo < x.mean() < hi and hi - lo < 0.01


def test_ece_idealnie_skalibrowany():
    rng = np.random.default_rng(1)
    p = rng.uniform(0, 1, 200_000)
    y = (rng.uniform(0, 1, p.size) < p).astype(int)
    assert evaluate.ece(p, y)[0] < 0.005
