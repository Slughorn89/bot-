"""Testy wlasciwosci (hypothesis): rynki, de-vig, Kelly, Elo. Sekcja 12.1: 100% galezi betting/ i markets/."""
import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from typer.betting.core import Limits, devig, edge, kelly_fraction, overround, select_and_stake
from typer.markets import football as mk
from typer.models.ratings.elo import Elo
from typer.models.scores.matrix import fast_markets, score_matrix

lam = st.floats(0.05, 6.0)
rho = st.floats(-0.2, 0.1)
odds_st = st.floats(1.01, 30.0)


@settings(max_examples=200, deadline=None)
@given(lam, lam, rho)
def test_macierz_sumuje_sie_do_1_i_jest_nieujemna(lh, la, r):
    m = score_matrix(lh, la, r)
    assert abs(m.sum() - 1) < 1e-9 and (m >= 0).all()


@settings(max_examples=200, deadline=None)
@given(lam, lam, rho)
def test_ou_monotoniczne_po_liniach(lh, la, r):
    m = score_matrix(lh, la, r)
    overs = [mk.p_ou(m, ln + 0.5)[f"over{ln + 0.5:g}"] for ln in range(0, 8)]
    assert all(a >= b - 1e-12 for a, b in zip(overs, overs[1:]))


@settings(max_examples=200, deadline=None)
@given(lam, lam, rho)
def test_ah0_to_dnb_i_1x2_z_macierzy_rowne_szybkiej_sciezce(lh, la, r):
    m = score_matrix(lh, la, r)
    p = mk.p_1x2(m)
    ah = mk.ah_probs(m, 0.0)
    assert abs(ah["win"] - p["1"]) < 1e-12 and abs(ah["push"] - p["X"]) < 1e-12  # AH 0 = DNB
    ph, pd_, pa, po, pb = fast_markets(lh, la, r)
    assert np.allclose([ph, pd_, pa], [p["1"], p["X"], p["2"]], atol=1e-12)
    assert abs(po - mk.p_ou(m, 2.5)["over2.5"]) < 1e-12 and abs(pb - mk.p_btts(m)["yes"]) < 1e-12


@settings(max_examples=200, deadline=None)
@given(st.lists(odds_st, min_size=2, max_size=4))
def test_devig_sumuje_sie_do_1_i_podnosi_kursy_przy_marzy(o):
    p = devig(o)
    assert abs(p.sum() - 1) < 1e-9
    if overround(o) >= 1:  # zdjeta marza: kurs fair >= kurs bukmachera
        assert np.all(1 / p >= np.asarray(o) - 1e-9)


@settings(max_examples=300, deadline=None)
@given(st.floats(0.001, 0.999), st.floats(0.5, 30.0), st.floats(0.0, 0.2))
def test_kelly_nigdy_ujemny_i_zero_bez_przewagi(p, o, tax):
    f = kelly_fraction(p, o, tax_rate=tax)
    assert f >= 0
    if edge(p, o, tax) <= 0 or o <= 1:
        assert f == 0


@settings(max_examples=150, deadline=None)
@given(st.lists(st.tuples(st.integers(0, 30), st.floats(0.01, 0.99), st.floats(0.5, 15.0)), min_size=1, max_size=40))
def test_limity_zawsze_trzymane_i_kurs_do_1_odrzucony(c):
    cands = [dict(event_id=f"e{e}", market="1X2", selection="1", p=p, odds=o) for e, p, o in c]
    lim = Limits()
    out = select_and_stake(cands, lim, threshold=0.0)
    assert all(b["stake_frac"] <= lim.max_per_bet + 1e-12 and b["odds"] > 1 for b in out)
    assert sum(b["stake_frac"] for b in out) <= lim.max_per_day + 1e-12
    assert len({b["event_id"] for b in out}) == len(out)


@settings(max_examples=200, deadline=None)
@given(st.integers(0, 8), st.integers(0, 8), st.floats(1300, 1700), st.floats(1300, 1700))
def test_elo_suma_zmian_zero(gh, ga, rh, ra):
    e = Elo()
    e.r[("L", "A")], e.r[("L", "B")] = rh, ra
    before = rh + ra
    e.update("L", "A", "B", gh, ga)
    assert abs(e.rating("L", "A") + e.rating("L", "B") - before) < 1e-9


def test_elo_brak_zmiany_przy_wyniku_zgodnym_z_oczekiwaniem():
    e = Elo(home_adv=0)
    e.r[("L", "A")] = e.r[("L", "B")] = 1500.0
    assert e.update("L", "A", "B", 1, 1) == 0.0  # oczekiwanie 0.5, remis = 0.5
