"""Straznik zaleznosci: penaltyblog + scipy musza dopasowywac Dixona-Colesa poprawnie.

Skill ostrzega, ze nowsze scipy psulo dopasowanie modeli goli w starszym penaltyblog.
Test porownuje penaltyblog z niezalezna implementacja MLE (wazona wiarygodnosc Dixona-Colesa,
L-BFGS-B) na tej samej SYNTETYCZNEJ lidze. Rozjazd = aktualizacja scipy/penaltyblog cos zepsula."""
import numpy as np
import pytest
from scipy.optimize import minimize

pb = pytest.importorskip("penaltyblog")


def _dc_nll(theta, hi, ai, gh, ga, w, n):
    atk, dfn = theta[:n], theta[n:2 * n]
    home, rho = theta[2 * n], theta[2 * n + 1]
    lh = np.exp(home + atk[hi] + dfn[ai])
    la = np.exp(atk[ai] + dfn[hi])
    tau = np.ones_like(lh)
    m00, m01, m10, m11 = (gh == 0) & (ga == 0), (gh == 0) & (ga == 1), (gh == 1) & (ga == 0), (gh == 1) & (ga == 1)
    tau[m00] = 1 - lh[m00] * la[m00] * rho
    tau[m01] = 1 + lh[m01] * rho
    tau[m10] = 1 + la[m10] * rho
    tau[m11] = 1 - rho
    from scipy.special import gammaln
    ll = (np.log(np.clip(tau, 1e-10, None)) + gh * np.log(lh) - lh - gammaln(gh + 1)
          + ga * np.log(la) - la - gammaln(ga + 1))
    return -(w * ll).sum() + 1e3 * atk.sum() ** 2  # identyfikowalnosc: suma atakow = 0


def _ref_probs(theta, h, a, n, max_goals=10):
    from typer.models.scores.matrix import score_matrix
    atk, dfn, home, rho = theta[:n], theta[n:2 * n], theta[2 * n], theta[2 * n + 1]
    m = score_matrix(np.exp(home + atk[h] + dfn[a]), np.exp(atk[a] + dfn[h]), rho)
    return float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())


@pytest.mark.slow
def test_penaltyblog_zgodny_z_niezaleznym_mle(synth):
    from penaltyblog.models import DixonColesGoalModel, dixon_coles_weights
    import pandas as pd
    d = synth[synth["league"] == "L1"]
    teams = sorted(set(d["home"]) | set(d["away"]))
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    w = dixon_coles_weights(pd.to_datetime(d["date"]), xi=0.0018, base_date=pd.to_datetime(d["date"]).max())
    m = DixonColesGoalModel(d["fthg"].astype(int), d["ftag"].astype(int), d["home"], d["away"], weights=w)
    m.fit()
    hi, ai = d["home"].map(ix).to_numpy(), d["away"].map(ix).to_numpy()
    gh, ga = d["fthg"].to_numpy(float), d["ftag"].to_numpy(float)
    x0 = np.r_[np.zeros(2 * n), 0.25, -0.05]
    ref = minimize(_dc_nll, x0, args=(hi, ai, gh, ga, np.asarray(w), n), method="L-BFGS-B",
                   bounds=[(-3, 3)] * (2 * n) + [(-1, 1), (-0.3, 0.3)])
    assert ref.success, ref.message
    worst = 0.0
    for h, a in [(teams[0], teams[1]), (teams[3], teams[7]), (teams[10], teams[2]), (teams[5], teams[11])]:
        g = m.predict(h, a, max_goals=10)
        p_pb = np.array(g.home_draw_away, float)
        p_ref = np.array(_ref_probs(ref.x, ix[h], ix[a], n))
        worst = max(worst, float(np.abs(p_pb - p_ref).max()))
    print(f"max roznica p(1X2) penaltyblog vs MLE: {worst:.5f}")
    assert worst < 0.01, f"penaltyblog rozjezdza sie z niezaleznym MLE o {worst:.4f}"
