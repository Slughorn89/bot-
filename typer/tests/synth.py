"""Generator SYNTETYCZNYCH lig do testow. To nie sa prawdziwe dane i nie trafiaja do raportow."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from typer.ingest import schema
from typer.models.scores.matrix import fast_markets


def make_league(league="L1", n_teams=12, seasons=4, start_year=2016, seed=0, home_adv=0.3,
                margin=1.05):
    rng = np.random.default_rng(seed)
    teams = [f"{league}-Team{i:02d}" for i in range(n_teams)]
    atk = rng.normal(0, 0.3, n_teams)
    dfn = rng.normal(0, 0.3, n_teams)
    rows = []
    for s in range(seasons):
        y = start_year + s
        atk += rng.normal(0, 0.05, n_teams)
        dfn += rng.normal(0, 0.05, n_teams)
        pairs = [(i, j) for i in range(n_teams) for j in range(n_teams) if i != j]
        rng.shuffle(pairs)
        # rozklad na kolejki: w kolejce kazda druzyna gra raz
        rounds, left = [], list(pairs)
        while left:
            used, rnd, rest = set(), [], []
            for p in left:
                if p[0] in used or p[1] in used:
                    rest.append(p)
                else:
                    rnd.append(p)
                    used |= {p[0], p[1]}
            rounds.append(rnd)
            left = rest
        first_sat = date(y, 8, 10) + timedelta(days=(5 - date(y, 8, 10).weekday()) % 7)
        for r, rnd in enumerate(rounds):
            d = first_sat + timedelta(days=7 * r)
            for h, a in rnd:
                lh = np.exp(0.1 + home_adv + atk[h] - dfn[a])
                la = np.exp(0.1 + atk[a] - dfn[h])
                gh, ga = rng.poisson(lh), rng.poisson(la)
                hst, ast = rng.poisson(lh / 0.27 * 0.8), rng.poisson(la / 0.27 * 0.8)
                ph, pd_, pa, po, _ = fast_markets(lh, la, -0.05)
                noise = lambda: float(np.exp(rng.normal(0, 0.03)))
                rows.append(dict(
                    league=league, season=f"{y}-{(y + 1) % 100:02d}", date=d,
                    kickoff_utc=pd.Timestamp(f"{d} 15:00", tz="UTC"), time_known=True,
                    home=teams[h], away=teams[a], fthg=gh, ftag=ga, hthg=np.nan, htag=np.nan,
                    hs=hst + rng.poisson(6), as_=ast + rng.poisson(6), hst=hst, ast=ast,
                    hr=int(rng.random() < 0.05), ar=int(rng.random() < 0.05),
                    odds_h=1 / (ph * margin) * noise(), odds_d=1 / (pd_ * margin) * noise(),
                    odds_a=1 / (pa * margin) * noise(), odds_o25=1 / (po * margin) * noise(),
                    odds_u25=1 / ((1 - po) * margin) * noise(), sport="football", source="synth"))
    df = pd.DataFrame(rows)
    for c in schema.COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    df["event_id"] = [schema.make_event_id(l, d, h, a) for l, d, h, a in
                      zip(df["league"], df["date"], df["home"], df["away"])]
    return df[schema.COLUMNS]


def make_matches(seed=0, seasons=4):
    a = make_league("L1", seed=seed, seasons=seasons)
    b = make_league("L2", seed=seed + 100, seasons=seasons, home_adv=0.15)
    df = pd.concat([a, b], ignore_index=True).sort_values(["kickoff_utc", "league", "home"])
    return schema.validate(df.reset_index(drop=True))
