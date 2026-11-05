"""Publiczne API modelu goli (modul 2).

    gm = GoalModel(variant="bivariate", half_life=480, w_xg=0.2).fit(mecze_ligi, cutoff)
    out = gm.predict("Arsenal", "Chelsea", cov_h, cov_a)
    out["matrix"]   # 11x11, P(gole gospodarza = i, gole goscia = j), suma 1
    out["markets"]  # 1X2, O/U 0.5..5.5, BTTS, AH -2.5..+2.5 (markets.football.market_bundle)

Wariant i parametry per liga wybiera backtest (pipeline/goal_backtest.py, config/model.yaml: goal_models).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from typer.markets.football import market_bundle
from typer.models.goals.distributions import VARIANTS, fit_extra, matrix
from typer.models.goals.fit import Strengths, fit_strengths


@dataclass
class GoalModel:
    variant: str = "dc"
    half_life: float = 480.0
    w_xg: float = 0.2
    ridge: float = 3.0
    window_days: int = 1095
    strengths: Strengths | None = None
    extra: float | None = None
    info: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.variant not in VARIANTS:
            raise ValueError(f"nieznany wariant {self.variant}; dostepne: {VARIANTS}")

    def fit(self, matches: pd.DataFrame, cutoff, cov_h=None, cov_a=None, promoted: set | None = None) -> "GoalModel":
        """matches: mecze JEDNEJ ligi. Uzywa wylacznie meczow rozegranych przed odcieciem (as of)."""
        d = pd.to_datetime(matches["date"])
        cut = pd.Timestamp(cutoff)
        tr = (matches["fthg"].notna() & matches["ftag"].notna() & (d < cut) &
              (d >= cut - pd.Timedelta(days=self.window_days))).to_numpy()
        if tr.sum() < 50:
            raise ValueError(f"za malo meczow przed {cut.date()} ({int(tr.sum())}) do dopasowania")
        ch = None if cov_h is None else np.asarray(cov_h)[tr]
        ca = None if cov_a is None else np.asarray(cov_a)[tr]
        self.strengths, data = fit_strengths(matches[tr], cut, self.half_life, self.w_xg, self.ridge,
                                             cov_h=ch, cov_a=ca, promoted=promoted)
        self.extra = fit_extra(self.variant, data["gh"], data["ga"], data["mh"], data["ma"], data["w"])
        self.info = dict(n=int(tr.sum()), converged=data["converged"], cutoff=str(cut.date()))
        return self

    def predict(self, home: str, away: str, cov_h=None, cov_a=None) -> dict:
        if self.strengths is None:
            raise RuntimeError("najpierw fit()")
        mh, ma = self.strengths.rates(home, away, cov_h, cov_a)
        m = matrix(self.variant, mh, ma, self.extra)
        return dict(variant=self.variant, mh=mh, ma=ma, extra=self.extra, matrix=m, markets=market_bundle(m))
