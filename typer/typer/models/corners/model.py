"""Publiczne API modelu rożnych (modul 3).

    gm = GoalModel("bivariate", half_life=240, w_xg=0.2).fit(mecze_ligi, cutoff)       # modul 2
    cm = CornerModel().fit(mecze_ligi, cutoff)             # wersja A (bez stanu gry), parametry z config/model.yaml
    out = cm.predict("Arsenal", "Chelsea", score_matrix=gm.predict("Arsenal", "Chelsea")["matrix"])
    out["joint"]    # 51x51, P(rozne gospodarza = i, rozne goscia = j)
    out["markets"]  # O/U lacznie 6.5..13.5, per druzyna 2.5..7.5, handicap -5..+5, kto wiecej rożnych

Parametry i wybor wersji (ze stanem gry czy bez): config/model.yaml, sekcja corner_models.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from typer.models.corners.fit import CornerStrengths, fit_corners
from typer.models.corners.markets import corner_markets
from typer.models.corners.simulate import N_SIMS, corner_distribution


@dataclass
class CornerModel:
    half_life: float = 365.0
    ridge: float = 3.0
    state: bool = False              # decyzja z backtestu: bez stanu gry (experiments.md, wpisy 22-23)
    frailty: bool = True
    window_days: int = 1095
    n_sims: int = N_SIMS
    strengths: CornerStrengths | None = None
    info: dict = field(default_factory=dict)

    def fit(self, matches: pd.DataFrame, cutoff, cov_h=None, cov_a=None) -> "CornerModel":
        """matches: mecze JEDNEJ ligi z kolumnami hc, ac (i hthg, htag dla stanu gry). Tylko mecze sprzed odciecia."""
        d = pd.to_datetime(matches["date"])
        cut = pd.Timestamp(cutoff)
        tr = (matches["hc"].notna() & matches["ac"].notna() & matches["fthg"].notna() & (d < cut) &
              (d >= cut - pd.Timedelta(days=self.window_days))).to_numpy()
        if tr.sum() < 100:
            raise ValueError(f"za malo meczow z rożnymi przed {cut.date()} ({int(tr.sum())})")
        ch = None if cov_h is None else np.asarray(cov_h)[tr]
        ca = None if cov_a is None else np.asarray(cov_a)[tr]
        self.strengths, _ = fit_corners(matches[tr], cut, self.half_life, self.ridge, state=self.state,
                                        frailty=self.frailty, cov_h=ch, cov_a=ca)
        s = self.strengths
        self.info = dict(n=int(tr.sum()), cutoff=str(cut.date()), g_trail=s.g_trail, g_lead=s.g_lead,
                         r=s.r, sigma=s.sigma, converged=s.info.get("converged"))
        return self

    def predict(self, home: str, away: str, score_matrix: np.ndarray | None = None, xh=None, xa=None,
                seed: int = 0) -> dict:
        if self.strengths is None:
            raise RuntimeError("najpierw fit()")
        out = corner_distribution(self.strengths, home, away, score_matrix, xh, xa, n_sims=self.n_sims, seed=seed)
        out["markets"] = corner_markets(out["joint"])
        out.pop("sim_scores", None)
        return out
