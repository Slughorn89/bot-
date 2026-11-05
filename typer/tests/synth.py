"""Generator syntetycznych predykcji do testow evaluate.py.
Prawdziwe p -> wynik; rynek = p_true + szum + marza; model = p_true + szum (uczciwy) albo z wyciekiem.
"""
import numpy as np
import pandas as pd


def _norm(p):
    return p / p.sum(axis=1, keepdims=True)


def make(n=1500, kind="honest", seed=1, ou_single=True, margin=0.05, start="2024-08-01"):
    rng = np.random.default_rng(seed)
    dates = pd.Timestamp(start) + pd.to_timedelta(np.sort(rng.integers(0, 600, n)), unit="D")
    s = rng.normal(0, 0.6, n)
    raw = np.c_[np.exp(s + 0.25), np.full(n, 1.05), np.exp(-s)]
    p_true = _norm(raw)
    res = np.array([rng.choice(3, p=p) for p in p_true])
    out = np.eye(3)[res]
    p_mkt = _norm(np.clip(p_true * np.exp(rng.normal(0, 0.04, (n, 3))), 1e-3, None))
    p_early = _norm(np.clip(p_true * np.exp(rng.normal(0, 0.12, (n, 3))), 1e-3, None))
    if kind == "honest":
        p_mod = _norm(np.clip(p_true * np.exp(rng.normal(0, 0.06, (n, 3))), 1e-3, None))
    elif kind == "leak":
        p_mod = _norm(0.5 * p_true + 0.5 * out + 1e-3)
    elif kind == "random":
        p_mod = np.full((n, 3), 1 / 3)
    elif kind == "bad_sum":
        p_mod = np.clip(p_true * 1.06, None, 0.99)
    else:
        raise ValueError(kind)
    p_base = _norm(np.c_[np.full(n, 0.45), np.full(n, 0.27), np.full(n, 0.28)])
    rows = []
    for i in range(n):
        for j, sel in enumerate("1X2"):
            rows.append(dict(event_id=f"e{i}", date=dates[i].date(), sport="pilka",
                             league=f"L{i % 3}", market="1X2", selection=sel,
                             p_model=p_mod[i, j], p_baseline=p_base[i, j], outcome=int(out[i, j]),
                             odds_taken=round(1 / (p_early[i, j] * (1 + margin)), 3),
                             odds_close=round(1 / (p_mkt[i, j] * (1 + margin)), 3)))
        if ou_single:  # rynek binarny w jednym wierszu, bez kursow zamkniecia
            po = rng.uniform(0.35, 0.65)
            rows.append(dict(event_id=f"e{i}", date=dates[i].date(), sport="pilka",
                             league=f"L{i % 3}", market="OU2.5", selection="over2.5",
                             p_model=po, p_baseline=0.5, outcome=int(rng.random() < po),
                             odds_taken=np.nan, odds_close=np.nan))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import sys
    make(kind=sys.argv[1] if len(sys.argv) > 1 else "honest").to_csv(sys.stdout, index=False)
