"""Cechy druzyn liczone wylacznie z meczow juz rozliczonych w chwili typowania."""
from __future__ import annotations

from collections import deque


class TeamForm:
    """Forma druzyny: wygaszane srednie goli i proxy xG za/przeciw, punkty z ostatnich 5 meczow."""

    def __init__(self, halflife: float = 6.0):
        self.a = 1 - 0.5 ** (1 / halflife)
        self.ewm: dict[tuple[str, str], dict[str, float]] = {}
        self.pts: dict[tuple[str, str], deque] = {}
        self.last_played: dict[tuple[str, str], object] = {}

    def update(self, lg, team, date, gf, ga, xgf=None, xga=None):
        k = (lg, team)
        e = self.ewm.setdefault(k, {"gf": 1.3, "ga": 1.3, "xgf": 1.3, "xga": 1.3})
        e["gf"] += self.a * (gf - e["gf"])
        e["ga"] += self.a * (ga - e["ga"])
        if xgf is not None and xga is not None:
            e["xgf"] += self.a * (xgf - e["xgf"])
            e["xga"] += self.a * (xga - e["xga"])
        self.pts.setdefault(k, deque(maxlen=5)).append(3 if gf > ga else 1 if gf == ga else 0)
        self.last_played[k] = date

    def features(self, lg, team, prefix: str) -> dict:
        k = (lg, team)
        e = self.ewm.get(k, {"gf": 1.3, "ga": 1.3, "xgf": 1.3, "xga": 1.3})
        p = self.pts.get(k)
        return {f"{prefix}gf_ewm": e["gf"], f"{prefix}ga_ewm": e["ga"],
                f"{prefix}xgf_ewm": e["xgf"], f"{prefix}xga_ewm": e["xga"],
                f"{prefix}pts5": (sum(p) / len(p)) if p else 1.35}
