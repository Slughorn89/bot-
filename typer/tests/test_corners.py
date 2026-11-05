"""Modul 3: rzuty rozne. Oś stanu gry, symulacja zgodna z macierza modulu 2, B == A przy gamma = 0,
spojnosc rynkow, zachowanie srednich, odzyskiwanie parametrow (gamma, r, sigma, sily), podroz w czasie cech,
powtarzalnosc ziarna, czas liczenia."""
import time

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from scipy.stats import chisquare

from typer.features.asof import prediction_cutoff
from typer.features.corners_style import STYLE_NAMES, style_features
from typer.models.corners import markets as mk
from typer.models.corners.fit import CornerStrengths, fit_corners, fit_dispersion
from typer.models.corners.model import CornerModel
from typer.models.corners.simulate import N_SIMS, corner_distribution, joint_pmf
from typer.models.corners.state import (expected_fractions, multipliers, simulate_states, timeline_library,
                                        _fractions)
from typer.models.goals.distributions import matrix
from typer.pipeline.corner_backtest import compare, match_losses, paired_ci


def _strengths(state=True, gT=0.1, gL=-0.2, r=40.0, sigma=0.15):
    return CornerStrengths(c=1.5, home=0.15, atk={"X": 0.1, "Y": -0.1}, obr={"X": 0.05, "Y": -0.05},
                           beta=np.zeros(0), g_trail=gT, g_lead=gL, r=r, sigma=sigma, p1=0.45, state=state)


# ---------------- os stanu gry ----------------
def test_udzialy_czasu_proste_przypadki():
    assert expected_fractions(0, 0, 0, 0) == (0.0, 0.0)
    lead, trail = expected_fractions(1, 0, 1, 0, draws=20000)
    assert abs(lead - 0.75) < 0.005 and trail == 0.0           # gol jednostajnie w 1. polowie: E = (90-22.5)/90
    lead, trail = expected_fractions(0, 0, 0, 1, draws=20000)
    assert lead == 0.0 and abs(trail - 0.25) < 0.005           # gol gosci w 2. polowie: E = 22.5/90
    # deterministycznie: gol gospodarza w 30. minucie, wyrownanie w 60.
    l, t = _fractions(np.array([[30.0, 60.0]]), np.array([[1, -1]]))
    assert abs(l[0] - 30 / 90) < 1e-12 and t[0] == 0.0


def test_biblioteka_przebiegow_zgodna_z_p1():
    p1 = 0.4
    lead, trail = timeline_library(p1, k=20000)
    e_t = p1 * 22.5 + (1 - p1) * 67.5                           # oczekiwana minuta jedynego gola
    assert abs(lead[1, 0].mean() - (90 - e_t) / 90) < 0.005
    assert abs(trail[0, 1].mean() - (90 - e_t) / 90) < 0.005
    assert (lead + trail <= 1 + 1e-6).all() and (lead >= 0).all()
    assert lead[0, 0].max() == 0 and trail[0, 0].max() == 0


def test_mnozniki_stanu_symetria():
    Mh, Ma = multipliers(0.5, 0.2, 0.3, -0.2)
    assert abs(Mh - (0.3 + 0.2 * np.exp(0.3) + 0.5 * np.exp(-0.2))) < 1e-12
    assert abs(Ma - (0.3 + 0.5 * np.exp(0.3) + 0.2 * np.exp(-0.2))) < 1e-12   # gosc przegrywa, gdy dom prowadzi
    assert multipliers(0.4, 0.3, 0.0, 0.0) == (1.0, 1.0)


# ---------------- symulacja zgodna z macierza modulu 2 ----------------
def test_symulowane_wyniki_zgodne_z_macierza_modulu_2():
    m = matrix("bivariate", 1.6, 1.1, 0.1)
    _, _, w, scores = simulate_states(m, 0.45, N_SIMS, np.random.default_rng(3))
    assert len(scores) == N_SIMS >= 20000 and abs(w.sum() - 1) < 1e-12
    obs = np.zeros_like(m)
    np.add.at(obs, (scores[:, 0], scores[:, 1]), 1)
    exp = m / m.sum() * N_SIMS
    keep = exp >= 5
    rest_o, rest_e = obs[~keep].sum(), exp[~keep].sum()
    stat = chisquare(np.r_[obs[keep], rest_o], np.r_[exp[keep], rest_e] * N_SIMS / (exp[keep].sum() + rest_e))
    assert stat.pvalue > 0.001


def test_wersja_ze_stanem_rowna_bez_stanu_gdy_gamma_zero():
    m = matrix("bivariate", 1.5, 1.2, 0.1)
    a = corner_distribution(_strengths(state=False, gT=0, gL=0), "X", "Y")
    b = corner_distribution(_strengths(state=True, gT=0, gL=0), "X", "Y", m, seed=1)
    assert np.abs(a["joint"] - b["joint"]).max() < 1e-12


def test_stan_gry_przesuwa_rozne_w_strone_slabszego():
    """Faworyt czesciej prowadzi, wiec przy gamma_L < 0 < gamma_T ma mniej rożnych niz bez stanu, a rywal wiecej."""
    m = matrix("bivariate", 2.4, 0.6, 0.05)
    a = corner_distribution(_strengths(state=False, gT=0, gL=0), "X", "Y")
    b = corner_distribution(_strengths(state=True, gT=0.15, gL=-0.25), "X", "Y", m)
    ma, mb = mk.corner_markets(a["joint"]), mk.corner_markets(b["joint"])
    assert mb["mean_home"] < ma["mean_home"] and mb["mean_away"] > ma["mean_away"]


def test_ziarno_powtarzalne_a_szum_mc_maly():
    m = matrix("bivariate", 1.5, 1.2, 0.1)
    s = _strengths()
    p1 = corner_distribution(s, "X", "Y", m, seed=5)["joint"]
    p2 = corner_distribution(s, "X", "Y", m, seed=5)["joint"]
    p3 = corner_distribution(s, "X", "Y", m, seed=6)["joint"]
    assert np.array_equal(p1, p2)
    m1, m3 = mk.corner_markets(p1), mk.corner_markets(p3)
    assert abs(m1["total"][9.5]["over"] - m3["total"][9.5]["over"]) < 2e-3


def test_czas_20000_symulacji():
    m = matrix("bivariate", 1.5, 1.2, 0.1)
    s = _strengths()
    corner_distribution(s, "X", "Y", m)                          # rozgrzanie biblioteki przebiegow
    t = time.perf_counter()
    for k in range(10):
        corner_distribution(s, "X", "Y", m, seed=k)
    assert (time.perf_counter() - t) / 10 < 0.25


# ---------------- rozklad laczny i rynki ----------------
@settings(max_examples=40, deadline=None)
@given(mh=st.floats(1.5, 9.0), ma=st.floats(1.5, 9.0), r=st.floats(3.0, 500.0), sigma=st.floats(0.0, 0.5))
def test_rozklad_zachowuje_srednie_i_rynki_sa_spojne(mh, ma, r, sigma):
    P = joint_pmf(mh, ma, r, sigma)
    assert abs(P.sum() - 1) < 1e-9 and (P >= 0).all()
    b = mk.corner_markets(P)
    assert abs(b["mean_home"] - mh) < 0.01 * mh and abs(b["mean_away"] - ma) < 0.01 * ma   # frailty nie zmienia srednich
    assert abs(b["mean_total"] - b["mean_home"] - b["mean_away"]) < 1e-9
    tot = mk.total_pmf(P)
    i, j = np.indices(P.shape)
    assert abs(b["total"][9.5]["over"] - P[i + j > 9.5].sum()) < 1e-12         # O/U laczne z przekatnych
    assert abs(tot.sum() - 1) < 1e-9
    overs = [b["total"][x]["over"] for x in mk.TOTAL_LINES]
    assert all(a >= c - 1e-12 for a, c in zip(overs, overs[1:]))               # monotoniczne
    for side in ("home", "away"):
        o = [b[side][x]["over"] for x in mk.TEAM_LINES]
        assert all(a >= c - 1e-12 for a, c in zip(o, o[1:]))
    assert abs(b["home"][4.5]["over"] - P[5:, :].sum()) < 1e-12
    for line, v in b["handicap"].items():
        assert abs(v["home"] + v["away"] + v["push"] - 1) < 1e-9
        if line != int(line):
            assert v["push"] == 0
    assert abs(b["handicap"][0.0]["home"] - b["most_corners"]["home"]) < 1e-12
    assert abs(b["handicap"][0.0]["push"] - b["most_corners"]["draw"]) < 1e-12
    assert abs(b["handicap"][-1.5]["home"] - P[i - j >= 2].sum()) < 1e-12
    hs = [b["handicap"][x]["home"] for x in mk.HANDICAP_LINES]
    assert all(a <= c + 1e-12 for a, c in zip(hs, hs[1:]))                      # wiekszy plus = latwiej


def test_srednie_zachowane_w_rogu_zakresu_parametrow():
    """Regresja z CI: przy siatce 0..30 i r = 3, sigma = 0.5 srednia goscia wychodzila 6.91 zamiast 7.0."""
    b = mk.corner_markets(joint_pmf(2.0, 7.0, 3.0, 0.5))
    assert abs(b["mean_away"] - 7.0) < 0.01 * 7.0 and abs(b["mean_home"] - 2.0) < 0.01 * 2.0


def test_frailty_daje_ujemna_korelacje_i_wezsza_sume():
    P0, P1 = joint_pmf(5.3, 4.4, 40.0, 0.0), joint_pmf(5.3, 4.4, 40.0, 0.25)
    i, j = np.indices(P0.shape)

    def cov(P):
        return (P * i * j).sum() - (P * i).sum() * (P * j).sum()
    assert abs(cov(P0)) < 1e-9 and cov(P1) < -0.5


def test_log_loss_meczu():
    P = joint_pmf(5.0, 4.0, 30.0, 0.1)
    L = match_losses(P, 6, 3)
    assert abs(L["ll_joint"] + np.log(P[6, 3])) < 1e-12
    assert abs(L["ll_total"] + np.log(mk.total_pmf(P)[9])) < 1e-12
    assert abs(L["ll_ou95"] + np.log(1 - P[np.add.outer(np.arange(P.shape[0]), np.arange(P.shape[0])) > 9.5].sum())) < 1e-9


# ---------------- odzyskiwanie parametrow na danych syntetycznych ----------------
def _synth_league(n_rounds=12, gT=0.15, gL=-0.25, r=30.0, sigma=0.0, seed=0):
    """Liga 16 druzyn, pelne kolejki, gole z minutami (jednostajnie), rozne z intensywnosci zaleznej od stanu."""
    rng = np.random.default_rng(seed)
    teams = [f"T{i:02d}" for i in range(16)]
    atk = dict(zip(teams, rng.normal(0, 0.15, 16)))
    obr = dict(zip(teams, rng.normal(0, 0.15, 16)))
    rows, day = [], pd.Timestamp("2020-08-01")
    for _ in range(n_rounds):
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                gh, ga = rng.poisson(1.5), rng.poisson(1.15)
                t = rng.uniform(0, 90, gh + ga)
                lab = np.array([1] * gh + [-1] * ga)
                lead, trail = _fractions(t[None, :], lab[None, :]) if gh + ga else (np.zeros(1), np.zeros(1))
                Mh, Ma = multipliers(lead[0], trail[0], gT, gL)
                u = rng.normal(0, sigma)
                mh = np.exp(1.55 + 0.15 + atk[h] - obr[a]) * Mh * np.exp(u - sigma ** 2 / 2)
                ma = np.exp(1.55 + atk[a] - obr[h]) * Ma * np.exp(-u - sigma ** 2 / 2)
                hc = rng.negative_binomial(r, r / (r + mh))
                ac = rng.negative_binomial(r, r / (r + ma))
                rows.append(dict(date=day.date(), home=h, away=a, fthg=gh, ftag=ga,
                                 hthg=int((t[lab == 1] < 45).sum()), htag=int((t[lab == -1] < 45).sum()),
                                 hc=hc, ac=ac))
                day += pd.Timedelta(hours=8)
    return pd.DataFrame(rows), atk, obr


def test_odzyskanie_efektu_stanu_gry():
    df, _, _ = _synth_league(n_rounds=12, gT=0.15, gL=-0.25, seed=1)
    cut = pd.Timestamp(df["date"].max()) + pd.Timedelta(days=1)
    s, _ = fit_corners(df, cut, half_life=1e6, state=True, frailty=False, ridge_gamma=0.0)
    assert abs(s.g_trail - 0.15) < 0.07 and abs(s.g_lead + 0.25) < 0.07, (s.g_trail, s.g_lead)
    s0, _ = fit_corners(df, cut, half_life=1e6, state=False)
    assert s0.g_trail == 0.0 and s0.g_lead == 0.0


def test_odzyskanie_sil_druzyn_z_korekta_na_rywala():
    df, atk, obr = _synth_league(n_rounds=8, gT=0.0, gL=0.0, seed=2)
    cut = pd.Timestamp(df["date"].max()) + pd.Timedelta(days=1)
    s, _ = fit_corners(df, cut, half_life=1e6, ridge=0.5)
    t = sorted(atk)
    assert np.corrcoef([atk[x] for x in t], [s.atk[x] for x in t])[0, 1] > 0.85
    assert np.corrcoef([obr[x] for x in t], [s.obr[x] for x in t])[0, 1] > 0.85


def test_odzyskanie_rozproszenia_i_frailty():
    rng = np.random.default_rng(4)
    n, r, sigma = 6000, 25.0, 0.25
    mh, ma = rng.uniform(4, 7, n), rng.uniform(3, 6, n)
    u = rng.normal(0, sigma, n)
    lh, la = mh * np.exp(u - sigma ** 2 / 2), ma * np.exp(-u - sigma ** 2 / 2)
    yh = rng.negative_binomial(r, r / (r + lh))
    ya = rng.negative_binomial(r, r / (r + la))
    r_hat, s_hat = fit_dispersion(yh, ya, mh, ma, np.ones(n))
    assert abs(s_hat - sigma) < 0.06 and 10 < r_hat < 80, (r_hat, s_hat)


# ---------------- cechy stylu: podroz w czasie ----------------
def _style_df():
    df, _, _ = _synth_league(n_rounds=2, seed=3)
    df["league"] = "SYN"
    df["hs"], df["as_"] = 12.0, 10.0
    df["date"] = [pd.Timestamp("2020-08-01").date() + pd.Timedelta(days=k // 8) for k in range(len(df))]
    return df


def test_cechy_stylu_bez_podrozy_w_czasie():
    df = _style_df()
    ch, ca = style_features(df)
    assert ch.shape == (len(df), len(STYLE_NAMES))
    i = len(df) // 2
    cut = pd.Timestamp(prediction_cutoff(df.at[i, "date"]))
    later = pd.to_datetime(df["date"]) >= cut                           # wszystko od odciecia meczu i
    df2 = df.copy()
    df2.loc[later, ["hc", "ac", "hs", "as_"]] = [30, 0, 40, 1]
    ch2, ca2 = style_features(df2)
    assert np.allclose(ch[i], ch2[i]) and np.allclose(ca[i], ca2[i])
    early = pd.to_datetime(df["date"]) < cut - pd.Timedelta(days=4)
    df3 = df.copy()
    df3.loc[early, "hc"] = 25
    ch3, _ = style_features(df3)
    assert not np.allclose(ch[i], ch3[i])                                # przeszlosc wplywa, przyszlosc nie


def test_brak_pogody_daje_zero():
    ch, ca = style_features(_style_df())
    assert (ch[:, 5:] == 0).all() and (ca[:, 5:] == 0).all()


# ---------------- API i porownanie ----------------
def test_api_modelu_rożnych():
    df, _, _ = _synth_league(n_rounds=4, seed=5)
    cut = pd.Timestamp(df["date"].max()) + pd.Timedelta(days=1)
    cm = CornerModel(state=True, n_sims=20000).fit(df, cut)
    out = cm.predict("T00", "T01", score_matrix=matrix("bivariate", 1.5, 1.1, 0.1))
    assert out["joint"].shape == (51, 51) and abs(out["joint"].sum() - 1) < 1e-9
    assert set(out["markets"]) >= {"total", "home", "away", "handicap", "most_corners"}
    with pytest.raises(ValueError):
        CornerModel(state=True).fit(df, cut).predict("T00", "T01")          # B bez macierzy wynikow


def test_paired_ci_i_porownanie():
    rng = np.random.default_rng(0)
    ci = paired_ci(rng.normal(-0.01, 0.05, 4000))
    assert ci["ci95"][0] < ci["ci90"][0] < ci["mean"] < ci["ci90"][1] < ci["ci95"][1] < 0
    res = pd.DataFrame([dict(event_id=k, league="L", variant=v, ll_joint=1.0 + (0.01 if v == "B" else 0))
                        for k in range(50) for v in ("A", "B")])
    t = compare(res, "A", "B", metrics=["ll_joint"])
    assert abs(t.loc[0, "roznica"] - 0.01) < 1e-12 and t.loc[0, "n"] == 50
