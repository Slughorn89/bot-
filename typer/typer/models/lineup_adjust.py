"""Challenger "lineup": korekta oczekiwanych goli o braki w skladzie.

  log lam_h' = log lam_h - b * braki_h + g * braki_a
  log lam_a' = log lam_a - b * braki_a + g * braki_h

b = o ile brak pewniakow oslabia wlasny atak, g = o ile oslabia wlasna obrone (pomaga rywalowi).

Wspolczynnikow NIE zakladamy z gory: w historii nie mamy skladow, wiec startuja od 0 (challenger
= champion) i sa dopasowywane metoda najwiekszej wiarygodnosci Poissona na meczach rozliczonych
na zywo, z kara L2 ciagnaca je do 0 (KARA = 50, czyli przy malej probie praktycznie 0).
Awans challengera tylko przez learn/champion.py: >= 300 zdarzen i CI90 roznicy log loss < 0.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from typer import config

VERSION = "lineup-v1"
KARA = 50.0
STATE = config.ROOT / "live" / "lineup_params.json"


def adjust(lam_h, lam_a, braki_h, braki_a, b: float, g: float):
    mh = np.nan_to_num(np.asarray(braki_h, float))
    ma = np.nan_to_num(np.asarray(braki_a, float))
    return (np.asarray(lam_h) * np.exp(-b * mh + g * ma), np.asarray(lam_a) * np.exp(-b * ma + g * mh))


def fit(df: pd.DataFrame, kara: float = KARA) -> dict:
    """df: lam_h, lam_a, braki_h, braki_a, fthg, ftag (mecze rozliczone)."""
    d = df.dropna(subset=["lam_h", "lam_a", "fthg", "ftag"])
    d = d[d[["braki_h", "braki_a"]].notna().any(axis=1)]
    if d.empty:
        return dict(b=0.0, g=0.0, n=0)
    lh, la = d["lam_h"].to_numpy(float), d["lam_a"].to_numpy(float)
    mh, ma = np.nan_to_num(d["braki_h"].to_numpy(float)), np.nan_to_num(d["braki_a"].to_numpy(float))
    gh, ga = d["fthg"].to_numpy(float), d["ftag"].to_numpy(float)

    def nll(x):
        b, g = x
        eh, ea = -b * mh + g * ma, -b * ma + g * mh
        Lh, La = lh * np.exp(eh), la * np.exp(ea)
        val = -(gh * eh - Lh + ga * ea - La).sum() + 0.5 * kara * (b * b + g * g)
        grad_b = -((gh - Lh) * (-mh) + (ga - La) * (-ma)).sum() + kara * b
        grad_g = -((gh - Lh) * ma + (ga - La) * mh).sum() + kara * g
        return val, np.array([grad_b, grad_g])

    r = minimize(nll, np.zeros(2), jac=True, method="L-BFGS-B", bounds=[(-2, 2), (-2, 2)])
    return dict(b=float(r.x[0]), g=float(r.x[1]), n=int(len(d)))


def load_params(path: Path = STATE) -> dict:
    return json.loads(path.read_text()) if path.exists() else dict(b=0.0, g=0.0, n=0)


def save_params(p: dict, path: Path = STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(p))
