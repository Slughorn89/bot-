"""Silnik walk forward: jedna chronologiczna petla po meczach.

Dla kazdego dnia D:
  1. rozliczamy wszystkie mecze sprzed odciecia prediction_cutoff(D) (oceny, baseline, forma),
  2. typujemy mecze z dnia D wylacznie ze stanu sprzed odciecia.
Dzieki temu cechy sa "as of" z konstrukcji, a test podrozy w czasie to sprawdza.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import pandas as pd

from typer.features.asof import prediction_cutoff
from typer.features.football import TeamForm
from typer.models.baseline import LeagueFrequencies
from typer.models.ratings.elo import Elo
from typer.models.scores.matrix import fast_markets
from typer.models.scores.online_poisson import OnlinePoisson, Params

OUTCOME_COLS = ["fthg", "ftag", "hr", "ar"]


def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


class Engine:
    def __init__(self, params: Params | None = None, cutoff_mode: str = "fduk",
                 collect_features: bool = True):
        self.params = params or Params()
        self.model = OnlinePoisson(self.params)
        self.base = LeagueFrequencies()
        self.elo = Elo()
        self.form = TeamForm()
        self.cutoff_mode = cutoff_mode
        self.collect = collect_features
        self.season_count: dict[tuple[str, str], int] = defaultdict(int)
        self.applied: set[str] = set()

    # ---- nauka ----
    def apply(self, r) -> None:
        if r.event_id in self.applied:
            return
        lg = r.league
        self._season(lg, r.season)
        gh, ga = int(r.fthg), int(r.ftag)
        red = bool((_num(r.hr) or 0) + (_num(r.ar) or 0) > 0)
        self.model.update(lg, r.home, r.away, gh, ga, _num(r.hs), _num(r.as_), _num(r.hst),
                          _num(r.ast), red=red)
        self.base.update(lg, gh, ga)
        self.elo.update(lg, r.home, r.away, gh, ga)
        if self.collect:
            xh = self.model.xg_proxy(_num(r.hs), _num(r.hst))
            xa = self.model.xg_proxy(_num(r.as_), _num(r.ast))
            self.form.update(lg, r.home, r.date, gh, ga, xh, xa)
            self.form.update(lg, r.away, r.date, ga, gh, xa, xh)
        self.season_count[(lg, r.season)] += 1
        self.applied.add(r.event_id)

    def _season(self, lg: str, season: str) -> None:
        if self.model.season.get(lg) != season:
            first = lg not in self.model.season
            self.model.start_season(lg, season)
            if not first:
                self.elo.new_season(lg)

    # ---- typowanie ----
    def predict_row(self, r, last_date: dict) -> dict:
        lg = r.league
        self._season(lg, r.season)
        lh, la = self.model.rates(lg, r.home, r.away)
        ph, pdraw, pa, pover, pbtts = fast_markets(lh, la, self.model.lp(lg, "rho"))
        b = self.base.predict(lg)
        out = dict(event_id=r.event_id, league=lg, season=r.season, date=r.date,
                   kickoff_utc=r.kickoff_utc, home=r.home, away=r.away,
                   lam_h=lh, lam_a=la, p_h=ph, p_d=pdraw, p_a=pa, p_over=pover, p_btts=pbtts,
                   base_h=b["h"], base_d=b["d"], base_a=b["a"], base_over=b["over"],
                   base_btts=b["btts"])
        if self.collect:
            hs = self.model.teams[(lg, r.home)]
            as_ = self.model.teams[(lg, r.away)]
            eh, ea = self.elo.rating(lg, r.home), self.elo.rating(lg, r.away)
            d = pd.Timestamp(r.date)
            rest = lambda t: min((d - pd.Timestamp(last_date[(lg, t)])).days, 21) \
                if (lg, t) in last_date else 21
            out.update(atk_h=hs.atk, obr_h=hs.obr, atk_a=as_.atk, obr_a=as_.obr,
                       n_h=min(hs.n, 60), n_a=min(as_.n, 60),
                       home_adv=self.model.home[lg], mu=self.model.mu[lg],
                       elo_h=eh, elo_a=ea, elo_diff=eh - ea,
                       rest_h=rest(r.home), rest_a=rest(r.away),
                       month=d.month, season_progress=min(self.season_count[(lg, r.season)] / 380, 1.0))
            out.update(self.form.features(lg, r.home, "h_"))
            out.update(self.form.features(lg, r.away, "a_"))
        return out

    def run(self, matches: pd.DataFrame, predict_from=None, fixtures: pd.DataFrame | None = None
            ) -> pd.DataFrame:
        """matches: rozegrane mecze (wspolny schemat). fixtures: przyszle mecze do wytypowania.
        predict_from: od tej daty zapisujemy predykcje (wczesniej tylko nauka)."""
        df = matches.sort_values(["kickoff_utc", "league", "home"], kind="stable").reset_index(drop=True)
        allm = df if fixtures is None or fixtures.empty else pd.concat(
            [df, fixtures.assign(fthg=np.nan, ftag=np.nan)], ignore_index=True
        ).sort_values(["kickoff_utc", "league", "home"], kind="stable").reset_index(drop=True)
        played = df.itertuples(index=False)
        played_rows = list(played)
        ptr, n = 0, len(played_rows)
        pf = pd.Timestamp(predict_from).date() if predict_from is not None else None
        last_date: dict = {}
        out = []
        for d, day in allm.groupby("date", sort=True):
            cut = prediction_cutoff(d, self.cutoff_mode)
            touched = set()
            while ptr < n and played_rows[ptr].date < cut:
                self.apply(played_rows[ptr])
                touched.add(played_rows[ptr].league)
                ptr += 1
            for lg in touched:
                self.model.recenter(lg)
            if pf is None or d >= pf:
                for r in day.itertuples(index=False):
                    row = self.predict_row(r, last_date)
                    for c in OUTCOME_COLS:
                        row[c] = getattr(r, c, np.nan)
                    out.append(row)
            for r in day.itertuples(index=False):
                last_date[(r.league, r.home)] = r.date
                last_date[(r.league, r.away)] = r.date
        # dociagniecie nauki do konca (stan "na dzis" dla cyklu dziennego)
        while ptr < n:
            self.apply(played_rows[ptr])
            ptr += 1
        res = pd.DataFrame(out)
        if len(res):
            odds_cols = [c for c in matches.columns if c.startswith(("odds_", "max_", "close_", "bench_"))]
            src = allm.set_index("event_id")[odds_cols]
            res = res.join(src, on="event_id")
        return res
