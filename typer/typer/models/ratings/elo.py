"""Elo z marginesem zwyciestwa i przewaga gospodarza, osobno per liga.
Uzywane jako cecha (roznica ocen) i jako punkt odniesienia w testach."""
from __future__ import annotations

import math


class Elo:
    def __init__(self, k: float = 20.0, home_adv: float = 60.0, init: float = 1500.0,
                 promoted: float = 1440.0, season_regress: float = 0.2):
        self.k, self.home_adv, self.init = k, home_adv, init
        self.promoted, self.season_regress = promoted, season_regress
        self.r: dict[tuple[str, str], float] = {}

    def rating(self, lg: str, team: str) -> float:
        return self.r.get((lg, team), self.promoted if any(l == lg for l, _ in self.r) else self.init)

    def expected(self, lg: str, home: str, away: str) -> float:
        d = self.rating(lg, home) + self.home_adv - self.rating(lg, away)
        return 1 / (1 + 10 ** (-d / 400))

    def update(self, lg: str, home: str, away: str, gh: int, ga: int) -> float:
        """Zwraca zmiane oceny gospodarza (gosc dostaje dokladnie przeciwna: symetria)."""
        e = self.expected(lg, home, away)
        s = 1.0 if gh > ga else 0.5 if gh == ga else 0.0
        margin = abs(gh - ga)
        mult = 1.0 if margin <= 1 else (1.5 if margin == 2 else (11 + margin) / 8)
        delta = self.k * mult * (s - e)
        rh, ra = self.rating(lg, home), self.rating(lg, away)
        self.r[(lg, home)] = rh + delta
        self.r[(lg, away)] = ra - delta
        return delta

    def new_season(self, lg: str) -> None:
        teams = [k for k in self.r if k[0] == lg]
        if not teams:
            return
        mean = sum(self.r[k] for k in teams) / len(teams)
        for k in teams:
            self.r[k] = mean + (self.r[k] - mean) * (1 - self.season_regress)


def elo_prob(diff: float) -> float:
    return 1 / (1 + math.pow(10, -diff / 400))
