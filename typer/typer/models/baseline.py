"""Baseline: czestosci wynikow w lidze (wygaszane wykladniczo), liczone "as of".
To kolumna p_baseline w pliku predykcji. Model, ktory jej nie bije, nic nie wnosi."""
from __future__ import annotations

PRIOR = {"h": 0.45, "d": 0.26, "a": 0.29, "over": 0.50, "btts": 0.51}


class LeagueFrequencies:
    def __init__(self, halflife: float = 600.0, prior_n: float = 50.0):
        self.alpha = 1 - 0.5 ** (1 / halflife)
        self.state: dict[str, dict[str, float]] = {}
        self.prior_n = prior_n

    def _get(self, lg: str) -> dict[str, float]:
        if lg not in self.state:
            self.state[lg] = dict(PRIOR)
        return self.state[lg]

    def predict(self, lg: str) -> dict[str, float]:
        s = self._get(lg)
        tot = s["h"] + s["d"] + s["a"]
        return {"h": s["h"] / tot, "d": s["d"] / tot, "a": s["a"] / tot,
                "over": s["over"], "btts": s["btts"]}

    def update(self, lg: str, gh: int, ga: int) -> None:
        s = self._get(lg)
        a = self.alpha
        obs = {"h": float(gh > ga), "d": float(gh == ga), "a": float(gh < ga),
               "over": float(gh + ga > 2.5), "btts": float(gh > 0 and ga > 0)}
        for k, v in obs.items():
            s[k] += a * (v - s[k])
