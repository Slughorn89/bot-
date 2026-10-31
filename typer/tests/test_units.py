"""Testy jednostkowe (sekcja 12): Elo, macierz, rynki, de-vig, Kelly i limity."""
import numpy as np
import pytest

from typer.betting.core import Limits, devig, edge, kelly_fraction, select_and_stake
from typer.markets import football as mk
from typer.models.ratings.elo import Elo
from typer.models.scores.matrix import MAX_GOALS, score_matrix


def test_elo_symetryczne():
    e = Elo()
    before = e.rating("L", "A") + e.rating("L", "B")
    d = e.update("L", "A", "B", 3, 1)
    assert d > 0
    assert e.rating("L", "A") + e.rating("L", "B") == pytest.approx(before)
    # zamiana rol daje przeciwny znak oczekiwania bez przewagi gospodarza
    e2 = Elo(home_adv=0)
    assert e2.expected("L", "X", "Y") == pytest.approx(1 - e2.expected("L", "Y", "X"))


@pytest.mark.parametrize("lh,la,rho", [(1.4, 1.1, 0.0), (2.8, 0.4, -0.1), (6.0, 5.0, -0.05), (0.2, 0.2, 0.05)])
def test_macierz_sumuje_sie_do_1(lh, la, rho):
    m = score_matrix(lh, la, rho)
    assert m.shape == (MAX_GOALS + 1, MAX_GOALS + 1)
    assert m.sum() == pytest.approx(1.0, abs=1e-12)
    assert (m >= 0).all()


def test_rynki_spojne():
    m = score_matrix(1.7, 1.2, -0.06)
    p = mk.p_1x2(m)
    assert sum(p.values()) == pytest.approx(1.0)
    overs = [mk.p_ou(m, ln)[f"over{ln:g}"] for ln in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)]
    assert all(a > b for a, b in zip(overs, overs[1:])), "O/U musi byc monotoniczne po liniach"
    b = mk.p_btts(m)
    assert b["yes"] + b["no"] == pytest.approx(1.0)
    # AH 0 = remis zwraca stawke; -0.5 gospodarza = wygrana gospodarza w 1X2
    ah0 = mk.ah_probs(m, 0.0)
    assert ah0["push"] == pytest.approx(p["X"])
    assert mk.ah_probs(m, -0.5)["win"] == pytest.approx(p["1"])
    assert mk.ah_probs(m, 0.5)["win"] == pytest.approx(p["1"] + p["X"])
    # O/U z linia calkowita: over + under + zwrot = 1
    ou = mk.p_ou(m, 3.0)
    assert ou["over3"] + ou["under3"] + ou["push"] == pytest.approx(1.0)


def test_ah_cwiartkowa_to_srednia_dwoch_linii():
    m = score_matrix(1.5, 1.0, 0.0)
    ev = mk.ah_expected_profit(m, -0.75, 2.0)
    ev_a = mk.ah_expected_profit(m, -0.5, 2.0)
    ev_b = mk.ah_expected_profit(m, -1.0, 2.0)
    assert ev == pytest.approx((ev_a + ev_b) / 2)


def test_devig():
    p = devig([2.0, 3.4, 4.0])
    assert p.sum() == pytest.approx(1.0)
    raw = 1 / np.array([2.0, 3.4, 4.0])
    assert np.allclose(p, raw / raw.sum())
    assert devig([1.9, 1.9]) == pytest.approx([0.5, 0.5])


def test_kelly_i_limity():
    assert kelly_fraction(0.5, 2.0) == 0.0  # brak przewagi
    assert kelly_fraction(0.4, 2.0) == 0.0  # ujemna przewaga
    f = kelly_fraction(0.6, 2.0)
    assert f == pytest.approx(0.25 * (0.6 * 2 - 1) / 1)
    # podatek 12% zjada przewage
    assert edge(0.55, 2.0) > 0 and edge(0.55, 2.0, tax_rate=0.12) < 0
    lim = Limits()
    cands = [dict(event_id=f"e{i}", market="1X2", selection="1", p=0.7, odds=2.0) for i in range(20)]
    cands += [dict(event_id="e0", market="OU2.5", selection="over2.5", p=0.8, odds=2.0)]
    out = select_and_stake(cands, lim)
    assert all(b["stake_frac"] <= lim.max_per_bet + 1e-12 for b in out), "max 2% na zaklad"
    assert sum(b["stake_frac"] for b in out) <= lim.max_per_day + 1e-12, "max 10% dziennie"
    assert len({b["event_id"] for b in out}) == len(out), "jeden zaklad na mecz"
    # drawdown 25% od szczytu = brak nowych zakladow
    assert select_and_stake(cands, lim, bankroll=0.74, peak=1.0) == []


def test_kalibracja_poprawia_przesuniete_prawdopodobienstwa():
    from typer.models.calibration.calibrate import Binary, Multiclass
    rng = np.random.default_rng(0)
    p_true = rng.uniform(0.2, 0.8, 5000)
    y = (rng.random(5000) < p_true).astype(int)
    p_bad = np.clip(p_true ** 1.6, 0.01, 0.99)  # systematycznie zanizone
    ll = lambda p: -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    q = Binary("platt").fit(p_bad, y).transform(p_bad)
    assert ll(q) < ll(p_bad)
    P = np.c_[p_bad, 1 - p_bad]
    Q = Multiclass("vector").fit(P, 1 - y).transform(P)
    assert np.allclose(Q.sum(1), 1)
