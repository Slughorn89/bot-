"""Efekt stanu gry na rozne WEWNATRZ meczu (TheStatsAPI: minuty goli i roznych).

Model: dla kazdej pary (mecz, druzyna) liczba roznych w stanie s (remis / prowadzi / przegrywa) ~ Poisson(
  ekspozycja_s * exp(alfa_{mecz,druzyna} + gamma_s)), gamma_remis = 0. Efekt staly alfa usuwa wszystko, co jest
stale w danym meczu dla danej druzyny (styl, sila, dominacja, pogoda, sedzia): to byl powod odrzucenia wersji B
w module 3 (gamma z wynikow do przerwy i koncowych nie bylo przyczynowe). Estymacja warunkowa: w grupie
(mecz, druzyna) rozklad roznych po stanach jest wielomianowy z p_s ~ ekspozycja_s * exp(gamma_s).
Wariant z buforem: 5 minut przed kazdym golem wypada (naciska -> rozny i gol; odwrotna przyczynowosc).
CI z bootstrapu po meczach. Uzycie: python backtest/statsapi/state_effect.py E0 2425
"""
import json
import pickle
import sys

sys.path.insert(0, ".")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import minimize  # noqa: E402

from typer import config  # noqa: E402

STATES = ("level", "lead", "trail")


def timeline(recs):
    df = pd.DataFrame(recs)
    ev = df[df["_type"] == "MatchEvent"].copy()
    ev["extra_minute"] = ev["extra_minute"].fillna(0)
    res = df[df["_type"] == "MatchResult"][["home", "away", "kickoff_utc", "fthg", "ftag"]]
    return ev, res


def match_clock(g: pd.DataFrame) -> tuple[pd.Series, float]:
    """Czas ciagly w minutach: 1. polowa = minuta + doliczony (minuta <= 45), 2. polowa = dlugosc 1. polowy
    + (minuta - 45) + doliczony. Zwraca (t zdarzen, koniec meczu)."""
    first = g["minute"] <= 45
    h1 = 45 + float(g.loc[g["minute"] == 45, "extra_minute"].max() if (g["minute"] == 45).any() else 0)
    h2 = 45 + float(g.loc[g["minute"] == 90, "extra_minute"].max() if (g["minute"] == 90).any() else 0)
    t = np.where(first, g["minute"] + g["extra_minute"], h1 + (g["minute"] - 45) + g["extra_minute"])
    return pd.Series(t, index=g.index), h1 + h2


def goal_for_home(x, home) -> bool:
    """Gol dla gospodarza? Samobój: zrodlo przypisuje druzyne zawodnika (sprawdzane z wynikiem w __main__)."""
    return (x["team"] == home) != (x["type"] == "own_goal" and OWN_GOAL_TEAM_IS_SCORER)


OWN_GOAL_TEAM_IS_SCORER = True


def segments(ev, buffer: float = 0.0) -> pd.DataFrame:
    """Wiersze (mecz, druzyna, stan, ekspozycja_min, rozne)."""
    rows = []
    for (h, a, ko), g in ev.groupby(["home", "away", "kickoff_utc"]):
        t, end = match_clock(g)
        g = g.assign(t=t)
        goals = g[g["type"].isin(["goal", "penalty_scored", "own_goal"])].sort_values("t")
        cuts, diff, d = [0.0], [0], 0
        for _, x in goals.iterrows():
            d += 1 if goal_for_home(x, h) else -1
            cuts.append(float(x["t"]))
            diff.append(d)
        cuts.append(float(end))
        corners = g[g["type"] == "corner"]
        excl = [(tt - buffer, tt) for tt in goals["t"]] if buffer else []
        for i in range(len(diff)):
            lo, hi = cuts[i], cuts[i + 1]
            if hi <= lo:
                continue
            expo = hi - lo - sum(max(0.0, min(hi, b) - max(lo, a_)) for a_, b in excl)
            for team, sign in ((h, 1), (a, -1)):
                s = "level" if diff[i] == 0 else ("lead" if diff[i] * sign > 0 else "trail")
                c = corners[(corners["team"] == team) & (corners["t"] > lo) & (corners["t"] <= hi)]
                if excl:
                    c = c[[not any(a_ < tt <= b for a_, b in excl) for tt in c["t"]]]
                rows.append(dict(match=f"{h}|{a}|{ko}", team=team, state=s, expo=max(expo, 0.0), corners=len(c)))
    seg = pd.DataFrame(rows)
    return seg.groupby(["match", "team", "state"], as_index=False)[["expo", "corners"]].sum()


def check_goals(ev, res) -> float:
    """Odsetek meczow, w ktorych gole z przebiegu = wynik (kontrola parsowania i samobojow)."""
    ok = n = 0
    for (h, a, ko), g in ev.groupby(["home", "away", "kickoff_utc"]):
        r = res[(res["home"] == h) & (res["away"] == a) & (res["kickoff_utc"] == ko)]
        if r.empty:
            continue
        gl = g[g["type"].isin(["goal", "penalty_scored", "own_goal"])]
        hg = sum(goal_for_home(x, h) for _, x in gl.iterrows())
        n += 1
        ok += (hg, len(gl) - hg) == (int(r["fthg"].iloc[0]), int(r["ftag"].iloc[0]))
    return ok / max(n, 1)


def fit(seg: pd.DataFrame) -> dict:
    piv_c = seg.pivot_table(index=["match", "team"], columns="state", values="corners", fill_value=0)
    piv_e = seg.pivot_table(index=["match", "team"], columns="state", values="expo", fill_value=0)
    C = piv_c.reindex(columns=STATES, fill_value=0).to_numpy(float)
    E = piv_e.reindex(columns=STATES, fill_value=0).to_numpy(float)
    keep = (C.sum(1) > 0) & ((E > 0).sum(1) > 1)          # grupy bez zmiany stanu nic nie mowia o gamma
    C, E = C[keep], E[keep]

    def nll(g):
        lg = np.r_[0.0, g]
        w = E * np.exp(lg)
        p = w / w.sum(1, keepdims=True)
        return -np.sum(C * np.log(np.where(E > 0, p, 1.0)))
    r = minimize(nll, [0.0, 0.0], method="BFGS")
    return dict(g_lead=float(r.x[0]), g_trail=float(r.x[1]), grup=int(keep.sum()),
                rozne=int(C.sum()), minuty={s: float(E[:, i].sum()) for i, s in enumerate(STATES)})


def bootstrap(seg, n=300, seed=7):
    rng = np.random.default_rng(seed)
    ms = seg["match"].unique()
    by = {m: g for m, g in seg.groupby("match")}
    vals = []
    for _ in range(n):
        pick = rng.choice(ms, len(ms))
        s = pd.concat([by[m].assign(match=f"{m}#{k}") for k, m in enumerate(pick)])
        f = fit(s)
        vals.append((f["g_lead"], f["g_trail"]))
    v = np.array(vals)
    return {k: (float(np.percentile(v[:, j], 2.5)), float(np.percentile(v[:, j], 97.5))) for j, k in
            enumerate(("g_lead", "g_trail"))}


if __name__ == "__main__":
    lg, yr = sys.argv[1], sys.argv[2]
    recs = pickle.load(open(config.DATA_DIR / f"thestatsapi_{lg}_{yr}.pkl", "rb"))
    ev, res = timeline(recs)
    zg = check_goals(ev, res)
    if zg < 0.95:                       # moze zrodlo przypisuje samoboj druzynie, ktora zyskala bramke
        OWN_GOAL_TEAM_IS_SCORER = False
        zg2 = check_goals(ev, res)
        if zg2 <= zg:
            OWN_GOAL_TEAM_IS_SCORER = True
        zg = max(zg, zg2)
    print(f"gole z przebiegu zgodne z wynikiem: {zg:.1%} meczow", flush=True)
    out = {"zgodnosc_goli": zg, "samoboj_druzyna_strzelajacego": OWN_GOAL_TEAM_IS_SCORER}
    for name, buf in (("bez_bufora", 0.0), ("bufor_5min_przed_golem", 5.0)):
        seg = segments(ev, buf)
        f = fit(seg)
        f["ci95"] = bootstrap(seg)
        f["mnoznik_lead"], f["mnoznik_trail"] = float(np.exp(f["g_lead"])), float(np.exp(f["g_trail"]))
        out[name] = f
        print(name, json.dumps(f, indent=1, default=float), flush=True)
    json.dump(out, open(f"backtest/statsapi/state_effect_{lg}_{yr}.json", "w"), indent=1, default=float)
