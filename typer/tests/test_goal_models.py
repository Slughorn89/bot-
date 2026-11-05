"""Modul 2: model goli. Spojnosc rynkow z macierza dla kazdego wariantu, poprawnosc rozkladow,
odzyskiwanie parametrow, wagi czasowe, podroz w czasie cech, korekta skladu, wybor per liga."""
import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from typer.markets import football as mk
from typer.models.goals.distributions import (G, VARIANTS, bp_matrix, fit_extra, matrix, nb_matrix)
from typer.models.goals.fit import fit_strengths, make_objective, time_weights
from typer.models.scores.matrix import score_matrix

lam = st.floats(0.1, 4.0)
EXTRA = {"dc": st.floats(-0.2, 0.1), "bivariate": st.floats(0.0, 0.5), "negbin": st.floats(0.8, 500.0)}


# ---------------- test spojnosci (zamowiony w module 2) ----------------
@pytest.mark.parametrize("variant", VARIANTS)
@settings(max_examples=60, deadline=None)
@given(data=st.data())
def test_spojnosc_1x2_ou_btts_z_macierza(variant, data):
    mh, ma = data.draw(lam), data.draw(lam)
    x = data.draw(EXTRA[variant])
    m = matrix(variant, mh, ma, x)
    assert m.shape == (11, 11) and abs(m.sum() - 1) < 1e-9 and (m >= 0).all()
    p = mk.p_1x2(m)
    assert abs(p["1"] + p["X"] + p["2"] - 1) < 1e-12                          # suma 1X2 = 1
    tot = np.add.outer(G, G)
    assert abs(mk.p_ou(m, 2.5)["over2.5"] - m[tot >= 3].sum()) < 1e-12           # over 2.5 = komorki i+j >= 3
    btts = 1 - m[0, :].sum() - m[:, 0].sum() + m[0, 0]
    assert abs(mk.p_btts(m)["yes"] - btts) < 1e-12                             # BTTS z macierzy
    assert abs(mk.p_btts(m)["yes"] - m[1:, 1:].sum()) < 1e-12                  # to samo inaczej
    b = mk.market_bundle(m)
    overs = [b[f"OU{ln:g}"][f"over{ln:g}"] for ln in mk.OU_LINES]
    assert all(a >= c - 1e-12 for a, c in zip(overs, overs[1:]))               # O/U monotoniczne 0.5..5.5
    assert abs(b["AH+0"]["win"] - p["1"]) < 1e-12 and abs(b["AH+0"]["push"] - p["X"]) < 1e-12  # AH 0 = DNB
    for k, v in b.items():
        assert abs(sum(v.values()) - 1) < 1e-9, k


# ---------------- poprawnosc rozkladow ----------------
def test_dwuwymiarowy_poisson_srednie_i_kowariancja():
    m = bp_matrix(1.4, 1.0, 0.3)
    mx, my = (m.sum(1) * G).sum(), (m.sum(0) * G).sum()
    cov = (np.outer(G, G) * m).sum() - mx * my
    assert mx == pytest.approx(1.4, abs=1e-3) and my == pytest.approx(1.0, abs=1e-3)
    assert cov == pytest.approx(0.3 * 1.0, abs=1e-3)
    assert np.allclose(bp_matrix(1.4, 1.0, 0.0), score_matrix(1.4, 1.0, 0.0), atol=1e-12)


def test_ujemny_dwumianowy_wariancja_i_granica_poissona():
    m = nb_matrix(1.2, 0.9, 4.0)
    px = m.sum(1)
    mean = (px * G).sum()
    var = (px * G ** 2).sum() - mean ** 2
    assert mean == pytest.approx(1.2, abs=2e-3) and var == pytest.approx(1.2 + 1.2 ** 2 / 4, abs=2e-2)
    assert np.allclose(nb_matrix(1.2, 0.9, 1e6), score_matrix(1.2, 0.9, 0.0), atol=1e-5)


@pytest.mark.parametrize("variant,truth", [("negbin", 3.0), ("bivariate", 0.3)])
def test_profilowane_mle_odzyskuje_parametr(variant, truth):
    rng = np.random.default_rng(0)
    n = 20000
    mh, ma = np.full(n, 1.5), np.full(n, 1.1)
    if variant == "negbin":
        gh, ga = rng.negative_binomial(3, 3 / 4.5, n), rng.negative_binomial(3, 3 / 4.1, n)
    else:
        x3 = rng.poisson(0.33, n)
        gh, ga = rng.poisson(1.17, n) + x3, rng.poisson(0.77, n) + x3
    assert fit_extra(variant, gh, ga, mh, ma, np.ones(n)) == pytest.approx(truth, rel=0.1)


def test_dane_poissonowskie_daja_negbin_bez_nadmiernej_dyspersji():
    rng = np.random.default_rng(1)
    n = 20000
    r = fit_extra("negbin", rng.poisson(1.5, n), rng.poisson(1.1, n), np.full(n, 1.5), np.full(n, 1.1), np.ones(n))
    assert r > 100  # praktycznie Poisson


# ---------------- dopasowanie sily ----------------
def test_gradient_analityczny_zgodny_z_numerycznym():
    from scipy.optimize import approx_fprime
    rng = np.random.default_rng(2)
    n, N = 6, 400
    hi, ai = rng.integers(0, n, N), rng.integers(0, n, N)
    ai = np.where(ai == hi, (ai + 1) % n, ai)
    X = rng.normal(size=(N, 2))
    f = make_objective(hi, ai, n, rng.uniform(.2, 1, N), rng.poisson(1.4, N).astype(float),
                       rng.poisson(1.1, N).astype(float), X, X[::-1].copy(), np.zeros(n), np.zeros(n), 1.0, 1.0)
    th = rng.normal(0, 0.1, 2 + 2 * n + 2)
    assert np.allclose(f(th)[1], approx_fprime(th, lambda t: f(t)[0], 1e-6), rtol=1e-4, atol=1e-4)


def test_wagi_czasowe_half_life():
    w = time_weights(["2024-01-01", "2023-07-05", "2023-01-06"], "2024-01-01", 180)
    assert w[0] == pytest.approx(1.0) and w[1] == pytest.approx(0.5, abs=0.01) and w[2] == pytest.approx(0.25, abs=0.01)


def _toy_league(seed=0, n_teams=8, cycles=8, home=0.3):
    """Pelny terminarz: kazdy z kazdym u siebie i na wyjezdzie, powtorzony `cycles` razy."""
    rng = np.random.default_rng(seed)
    atk, obr = rng.normal(0, .35, n_teams), rng.normal(0, .35, n_teams)
    rows, d = [], pd.Timestamp("2020-08-01")
    pairs = [(h, a) for h in range(n_teams) for a in range(n_teams) if h != a]
    for c in range(cycles):
        for j, (h, a) in enumerate(pairs):
            gh = rng.poisson(np.exp(0.1 + home + atk[h] - obr[a]))
            ga = rng.poisson(np.exp(0.1 + atk[a] - obr[h]))
            rows.append(dict(home=f"T{h}", away=f"T{a}", fthg=gh, ftag=ga,
                             date=d + pd.Timedelta(days=c * len(pairs) + j)))
    return pd.DataFrame(rows), atk, obr


def test_sily_odzyskane_z_syntetycznej_ligi():
    df, atk, obr = _toy_league()
    s, _ = fit_strengths(df, df["date"].max() + pd.Timedelta(days=1), half_life=10_000, w_xg=0.0, ridge=0.5)
    est = np.array([s.atk[f"T{i}"] for i in range(len(atk))])
    est_o = np.array([s.obr[f"T{i}"] for i in range(len(obr))])
    assert s.home == pytest.approx(0.3, abs=0.1)
    assert np.corrcoef(est, atk)[0, 1] > 0.9 and np.corrcoef(est_o, obr)[0, 1] > 0.9


def test_beniaminek_bez_historii_dostaje_prior():
    df, _, _ = _toy_league()
    s, _ = fit_strengths(df, df["date"].max(), 365, 0.0, promoted_prior=(-0.25, -0.2))
    assert s.team("Nowy Klub") == (-0.25, -0.2)
    mh, ma = s.rates("T0", "Nowy Klub")
    mh2, _ = s.rates("T0", "T1")
    assert mh > 0 and ma > 0 and mh != mh2


# ---------------- cechy kontekstu i korekta skladu ----------------
def test_cechy_kontekstu_podroz_w_czasie(synth):
    from typer.features.context import context_features
    lg = synth[synth["league"] == "L1"].sort_values("kickoff_utc").reset_index(drop=True)
    cut = pd.Timestamp("2018-02-01").date()
    a_h, a_a = context_features(lg)
    fut = lg.copy()
    m = fut["date"] >= cut
    fut.loc[m, "fthg"], fut.loc[m, "ftag"] = 0, 5
    b_h, b_a = context_features(fut)
    past = (lg["date"] < cut).to_numpy()
    assert np.array_equal(a_h[past], b_h[past]) and np.array_equal(a_a[past], b_a[past])


def test_mecz_o_nic_tylko_pod_koniec_sezonu_i_z_tabeli():
    from typer.features.context import _table_dead
    teams = [f"T{i}" for i in range(20)]
    pts = {t: 80 - 3 * i for i, t in enumerate(teams)}   # 80, 77, ..., 23
    tot = {t: 38 for t in teams}
    early = _table_dead(pts, {t: 10 for t in teams}, tot)
    assert early == set()                                # 26% sezonu: nikt nie gra o nic
    late = _table_dead(pts, {t: 36 for t in teams}, tot)
    assert "T10" in late and "T0" not in late and "T19" not in late


def test_korekta_skladu():
    from typer.models.goals.lineup_adjust import apply_lineups, contributions, lineup_effect
    ko = pd.Timestamp("2024-08-17", tz="UTC")
    rows = []
    for k in range(5):
        for p, pos, xg in (("Snajper", "F", 0.7), ("Pomocnik", "M", 0.2), ("Obronca", "D", 0.02), ("Bramkarz", "G", 0.0)):
            rows.append(dict(team="A", player=p, position=pos, minutes=90, xg=xg, xa=0.05, kickoff_utc=ko - pd.Timedelta(days=7 * k),
                             available_at=ko - pd.Timedelta(days=7 * k) + pd.Timedelta(hours=3)))
    c = contributions(pd.DataFrame(rows), as_of=ko)
    full = lineup_effect(c, "A", {"Snajper", "Pomocnik", "Obronca", "Bramkarz"})
    assert full.atk_mult == pytest.approx(1.0) and full.obr_mult == pytest.approx(1.0)
    bez = lineup_effect(c, "A", {"Pomocnik", "Obronca", "Bramkarz"})
    assert bez.atk_mult < 0.7
    mh, ma = apply_lineups(1.6, 1.1, bez, lineup_effect(c, "B", set()))
    assert mh < 1.6 and ma == pytest.approx(1.1)
    # dane z przyszlosci (available_at po as_of) nie licza sie
    assert contributions(pd.DataFrame(rows), as_of=ko - pd.Timedelta(days=60)).empty


# ---------------- walk forward i wybor ----------------
def test_walk_forward_bez_wycieku_wlasnego_wyniku(synth):
    from typer.pipeline.goal_backtest import run_league
    lg = synth[synth["league"] == "L1"]
    a = run_league(lg, "2018-09-01", "2018-10-31", 365, 0.0, use_context=True)
    i = lg.index[(pd.to_datetime(lg["date"]) >= "2018-09-01")][0]
    alt = lg.copy()
    alt.loc[i, ["fthg", "ftag"]] = [9, 0]
    b = run_league(alt, "2018-09-01", "2018-10-31", 365, 0.0, use_context=True)
    eid = lg.loc[i, "event_id"]
    pa = a[(a.event_id == eid)].sort_values("variant")[["p_h", "p_over"]].to_numpy()
    pb = b[(b.event_id == eid)].sort_values("variant")[["p_h", "p_over"]].to_numpy()
    assert len(pa) == 3 and np.allclose(pa, pb)


def test_wybor_per_liga_tylko_przy_istotnej_poprawie():
    from typer.pipeline.goal_backtest import select_per_league
    rng = np.random.default_rng(3)
    n = 2000
    gh, ga = rng.poisson(1.5, n), rng.poisson(1.1, n)
    base = dict(event_id=[f"e{i}" for i in range(n)], league="L", fthg=gh, ftag=ga)

    def frame(lh, la):
        m = score_matrix(lh, la, 0.0)
        p = mk.p_1x2(m)
        return pd.DataFrame(dict(base, p_h=p["1"], p_d=p["X"], p_a=p["2"], p_over=mk.p_ou(m, 2.5)["over2.5"],
                                 p_btts=mk.p_btts(m)["yes"]))
    good, bad, noise = frame(1.5, 1.1), frame(1.2, 1.3), frame(1.51, 1.1)
    t = select_per_league({"domyslny": bad, "dobry": good}, default="domyslny")
    assert t.loc[0, "wybrany"] == "dobry"
    t = select_per_league({"domyslny": good, "szum": noise}, default="domyslny")
    assert t.loc[0, "wybrany"] == "domyslny"  # minimalna roznica: zostajemy przy domyslnym
