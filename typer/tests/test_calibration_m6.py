"""Modul 6: usuwanie marzy, metryki (Brier, log loss, ECE, wykresy), kalibracja z wyborem po ECE,
blend per liga, KPI (CLV, ROI z CI), tabela bet_clv."""
import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from scipy.optimize import brentq

from typer.betting import devig as dv
from typer.metrics import kpi, scores
from typer.metrics.plots import reliability_plot
from typer.models.calibration.select import calibrate_select_fn, select, uniform_choice
from typer.pipeline import layers as L

odds3 = st.lists(st.floats(1.05, 30.0), min_size=3, max_size=3)


# ---------------- usuwanie marzy ----------------
@settings(max_examples=80, deadline=None)
@given(o=odds3)
def test_devig_sumuje_do_1_dla_kazdej_metody(o):
    for m in dv.METHODS:
        p = dv.devig(np.array(o), m)
        assert abs(p.sum() - 1) < 1e-9 and (p > 0).all()
        assert np.all(np.argsort(p) == np.argsort(1 / np.array(o))) or len(set(o)) < 3   # kolejnosc zachowana


def test_brak_marzy_to_tozsamosc():
    p = np.array([0.5, 0.3, 0.2])
    for m in dv.METHODS:
        assert np.allclose(dv.devig(1 / p, m), p, atol=1e-9)


def test_shin_i_potegowa_zgodne_z_niezaleznym_rozwiazaniem():
    o = np.array([1.55, 4.2, 6.5])
    pi = 1 / o
    S = pi.sum()
    f = lambda z: ((np.sqrt(z ** 2 + 4 * (1 - z) * pi ** 2 / S) - z) / (2 * (1 - z))).sum() - 1
    z = brentq(f, 1e-9, 0.5)
    p_ref = (np.sqrt(z ** 2 + 4 * (1 - z) * pi ** 2 / S) - z) / (2 * (1 - z))
    p, zz = dv.shin(o, return_param=True)
    assert abs(zz - z) < 1e-9 and np.allclose(p, p_ref / p_ref.sum(), atol=1e-9)
    k = brentq(lambda k: (pi ** k).sum() - 1, 1.0, 5.0)
    pp, kk = dv.power(o, return_param=True)
    assert abs(kk - k) < 1e-9 and np.allclose(pp, pi ** k, atol=1e-9)


def test_faworyt_dostaje_wiecej_niz_w_proporcjonalnej():
    o = np.array([1.5, 4.0, 7.0])
    prop = dv.proportional(o)
    for m in ("shin", "power"):
        p = dv.devig(o, m)
        assert p[0] > prop[0] and p[2] < prop[2]          # marza zdejmowana glownie z outsidera


def test_devig_rows_daje_nan_dla_brakow():
    O = np.array([[2.0, 3.4, 3.6], [np.nan, 3.0, 2.5], [1.9, 1.95, np.nan]])
    P = dv.devig_rows(O, "shin")
    assert np.isfinite(P[0]).all() and np.isnan(P[1:]).all()


# ---------------- metryki ----------------
def test_brier_i_log_loss_na_znanych_przypadkach():
    assert scores.brier(np.array([1.0, 0.0]), np.array([1, 0])) == 0.0
    assert abs(scores.brier(np.array([[0.5, 0.3, 0.2]]), np.array([0])) - (0.25 + 0.09 + 0.04)) < 1e-12
    assert abs(scores.log_loss(np.array([[0.5, 0.3, 0.2]]), np.array([1])) + np.log(0.3)) < 1e-12
    assert abs(scores.log_loss(np.array([0.8]), np.array([0])) + np.log(0.2)) < 1e-12


def test_ece_zero_dla_skalibrowanych_i_wykrywa_przeuczenie():
    rng = np.random.default_rng(0)
    p = rng.uniform(0.05, 0.95, 200_000)
    y = (rng.random(p.size) < p).astype(float)
    assert scores.ece(p, y) < 0.005
    over = np.clip(0.5 + 1.6 * (p - 0.5), 0.01, 0.99)           # zbyt pewne
    assert scores.ece(over, y) > 0.05
    t = scores.reliability_table(p, y)
    assert t["n"].sum() == p.size and (t["ci_lo"] <= t["czestosc"]).all()


def test_wykres_zapisuje_png_i_csv(tmp_path):
    rng = np.random.default_rng(1)
    p = rng.uniform(0.1, 0.9, 3000)
    y = (rng.random(p.size) < p).astype(float)
    path = reliability_plot({"model": (p, y)}, tmp_path / "x" / "ou.png", title="test")
    assert path.exists() and path.stat().st_size > 5000
    assert len(pd.read_csv(path.with_suffix(".csv"))) == 10


def test_bootstrap_ci_pokrywa_srednia():
    rng = np.random.default_rng(2)
    x = rng.normal(0.3, 1, 5000)
    ci = scores.bootstrap_ci(lambda a: a.mean(), [x])
    assert ci["ci95"][0] < ci["ci90"][0] < 0.3 < ci["ci90"][1] < ci["ci95"][1]


# ---------------- KPI ----------------
def test_clv_przyklad_reczny():
    close = np.array([[2.0, 3.5, 4.0]])
    p_close = dv.devig(close[0], "proportional")
    c = kpi.clv([2.2], close, [0], "proportional")
    assert abs(c[0] - (2.2 * p_close[0] - 1)) < 1e-12
    assert np.isnan(kpi.clv([2.2], np.array([[np.nan, 3.5, 4.0]]), [0], "shin")[0])


def test_clv_nd_bez_ostrego_zamkniecia_i_jeden_zaklad_na_mecz():
    b = pd.DataFrame(dict(event_id=["a", "b"], stake=1.0, profit=[1.0, -1.0], clv=np.nan))
    r = kpi.bet_report(b)
    assert r["kpi_glowny"] == "CLV" and r["clv"]["clv"] == "n/d" and r["roi"]["roi"] == 0.0
    with pytest.raises(ValueError):
        kpi.bet_report(pd.DataFrame(dict(event_id=["a", "a"], stake=1.0, profit=[1.0, -1.0])))


def test_ci_roi_pokrywa_prawdziwe_roi():
    rng = np.random.default_rng(3)
    hits = 0
    for s in range(40):
        won = rng.random(1500) < 0.5
        prof = kpi.settle_profit(np.full(1500, 2.1), won)          # prawdziwe ROI = 0.5 * 2.1 - 1 = +5%
        r = kpi.roi_stats(np.ones(1500), prof, n_boot=400, seed=s)
        hits += r["roi_ci90"][0] <= 0.05 <= r["roi_ci90"][1]
    assert hits >= 32                                               # ok. 90% pokrycia


def test_podatek_obniza_zysk():
    assert kpi.settle_profit([2.0], [True], 1.0, 0.12)[0] == pytest.approx(0.76)
    assert kpi.settle_profit([2.0], [False], 1.0, 0.12)[0] == -1.0


# ---------------- kalibracja i blend na syntetycznej lidze ----------------
def _frame(n_seasons=6, per=900, over=1.5, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n_seasons):
        season = f"{2015 + s}-{str(2016 + s)[2:]}"
        for i in range(per):
            lg = "A" if i % 2 else "B"
            t = rng.dirichlet([4, 2.5, 3])
            P = np.exp(over * np.log(t))
            P /= P.sum()                                            # model zbyt pewny
            g = rng.choice(3, p=t)
            to = rng.uniform(0.35, 0.65)
            po = np.clip(0.5 + over * (to - 0.5), 0.02, 0.98)
            ov = rng.random() < to
            pb = rng.uniform(0.4, 0.6)
            gh, ga = {0: (2, 0), 1: (1, 1), 2: (0, 2)}[g]
            if ov and gh + ga < 3:
                gh += 2
            elif not ov and gh + ga > 2:
                gh, ga = (1, 0) if g == 0 else (0, 1) if g == 2 else (1, 1)
            m = t * 1.06
            rows.append(dict(event_id=f"{season}-{i}", league=lg, season=season,
                             date=pd.Timestamp(f"{2015 + s}-09-01") + pd.Timedelta(hours=6 * i),
                             p_h=P[0], p_d=P[1], p_a=P[2], p_over=po, p_btts=pb, fthg=gh, ftag=ga,
                             odds_h=1 / m[0], odds_d=1 / m[1], odds_a=1 / m[2],
                             odds_o25=1 / (to * 1.05), odds_u25=1 / ((1 - to) * 1.05),
                             close_h=np.nan, close_d=np.nan, close_a=np.nan))
    return pd.DataFrame(rows)


def test_kalibracja_obniza_ece_na_zbyt_pewnym_modelu():
    fr = _frame()
    seasons = sorted(fr["season"].unique())[3:]
    raw = fr[fr["season"].isin(seasons)]
    cal = L.walk_forward(fr, seasons, calibrate_select_fn(uniform_choice("vector_G", "platt_G")), train_from="2010-01-01")
    P0 = raw[L.P1X2].to_numpy()
    P1 = cal.loc[raw.index, L.P1X2].to_numpy()
    y = L.outcomes(raw)["1x2"]
    assert scores.ece(P1, y) < scores.ece(P0, y)
    assert scores.ece(cal["p_over"].to_numpy(), L.outcomes(raw)["over"]) < \
        scores.ece(raw["p_over"].to_numpy(), L.outcomes(raw)["over"])


def test_wybor_po_ece_i_bezpiecznik_log_loss():
    fr = _frame()
    seasons = sorted(fr["season"].unique())[3:]
    oof = {}
    for c1, cb in [("none", "none"), ("vector_G", "platt_G"), ("isotonic_G", "isotonic_G")]:
        out = L.walk_forward(fr, seasons, calibrate_select_fn(uniform_choice(c1, cb)), train_from="2010-01-01")
        oof[c1] = oof[cb] = out.sort_values("event_id").reset_index(drop=True)
    choice, tab = select(oof)
    assert choice["1X2"]["_global"] != "none" and choice["OU2.5"]["_global"] != "none"
    w = tab[(tab["wybrany"]) & (tab["liga"] == "_global") & (tab["rynek"] == "1X2")].iloc[0]
    sub = tab[(tab["liga"] == "_global") & (tab["rynek"] == "1X2") & tab["dopuszczony"]]
    assert w["ece_10q"] == sub["ece_10q"].min()
    assert set(choice["1X2"]) == {"_global", "A", "B"}


def test_kalibrator_sezonu_nie_widzi_jego_wynikow():
    fr = _frame(seed=4)
    seasons = sorted(fr["season"].unique())
    tgt = seasons[-1]
    fn = calibrate_select_fn(uniform_choice("vector_L", "platt_L"), min_rows=300)
    a = L.walk_forward(fr, [tgt], fn, train_from="2010-01-01")
    fr2 = fr.copy()
    m = fr2["season"] == tgt
    fr2.loc[m, ["fthg", "ftag"]] = fr2.loc[m, ["ftag", "fthg"]].to_numpy()   # zmiana wynikow sezonu S
    b = L.walk_forward(fr2, [tgt], fn, train_from="2010-01-01")
    assert np.allclose(a[L.P1X2].to_numpy(), b[L.P1X2].to_numpy())


def test_blend_per_liga_sciaga_do_globalnej_i_nie_widzi_zamkniec():
    fr = _frame(seed=5)
    seasons = sorted(fr["season"].unique())[-1:]
    g = L.walk_forward(fr, seasons, L.blend_fn(), train_from="2010-01-01")
    inf = L.walk_forward(fr, seasons, L.blend_fn(per_league=True, shrink_k=float("inf")), train_from="2010-01-01")
    assert np.allclose(g[L.P1X2].to_numpy(), inf[L.P1X2].to_numpy())
    pl = L.walk_forward(fr, seasons, L.blend_fn(per_league=True, shrink_k=0.0), train_from="2010-01-01")
    assert ((pl["w_model_1x2"] >= 0) & (pl["w_model_1x2"] <= 1)).all()
    fr2 = fr.copy()
    fr2[["close_h", "close_d", "close_a"]] = 1.01                    # absurdalne zamkniecie nie moze nic zmienic
    pl2 = L.walk_forward(fr2, seasons, L.blend_fn(per_league=True, shrink_k=0.0), train_from="2010-01-01")
    assert np.allclose(pl[L.P1X2].to_numpy(), pl2[L.P1X2].to_numpy())


def test_tabela_bet_clv_tylko_do_dopisywania(tmp_path):
    import sqlalchemy as sa
    from typer.store import db
    eng = db.get_engine(f"sqlite:///{tmp_path}/t.db")
    db.init_db(eng)
    db.append(eng, db.bet_clv, [dict(bet_id=1, event_id="e", market="1X2", selection="1", odds_taken=2.1,
                                     close_odds=2.0, close_odds_fair=2.08, close_book="pinnacle",
                                     devig_method="shin", clv=0.0096)])
    with pytest.raises(Exception):
        with eng.begin() as c:
            c.execute(sa.text("UPDATE bet_clv SET clv = 1"))


def test_zamkniecie_tylko_ostre_jeden_bukmacher_i_zapis_clv(tmp_path):
    from datetime import datetime, timezone
    from typer.learn import settle
    from typer.store import db
    eng = db.get_engine(f"sqlite:///{tmp_path}/t.db")
    db.init_db(eng)
    t = datetime(2026, 9, 1, 15, tzinfo=timezone.utc)
    snap = lambda e, b, sel, p, m="1X2": dict(event_id=e, source="x", bookmaker=b, market=m, selection=sel,
                                              price=p, kind="close", snapshot_utc=t, available_at=t, fetched_at=t)
    db.append(eng, db.odds_snapshots, [
        snap("e1", "pinnacle", "1", 2.0), snap("e1", "pinnacle", "X", 3.5), snap("e1", "pinnacle", "2", 4.0),
        snap("e2", "bet365", "1", 2.0), snap("e2", "bet365", "X", 3.5), snap("e2", "bet365", "2", 4.0),   # miekki
        snap("e3", "pinnacle", "1", 2.0), snap("e3", "pinnacle", "X", 3.5)])                            # niepelny
    co = settle.closing_odds(eng)
    assert set(co["event_id"]) == {"e1"} and (co["close_book"] == "pinnacle").all()
    pf = dv.devig(np.array([2.0, 3.5, 4.0]), settle._devig_method("1X2"))   # metoda z config/model.yaml
    assert abs(co.set_index("selection").loc["1", "odds_close_fair"] - 1 / pf[0]) < 1e-9
    db.append(eng, db.bets, [dict(prediction_id=1, event_id="e1", market="1X2", selection="1", odds=2.2, edge=0.05,
                                  stake_frac=0.01), dict(prediction_id=2, event_id="e2", market="1X2", selection="1",
                                                         odds=2.2, edge=0.05, stake_frac=0.01)])
    assert settle.record_clv(eng) == 1 and settle.record_clv(eng) == 0          # bez duplikatow
    r = db.read_df(eng, "SELECT * FROM bet_clv")
    assert r.loc[0, "event_id"] == "e1" and abs(r.loc[0, "clv"] - (2.2 * pf[0] - 1)) < 1e-9
