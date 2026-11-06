"""Champion (oceny online) z prawdziwym xG (TheStatsAPI) zamiast przyblizenia ze strzalow, per liga.

Ocena: J = ll 1X2 + 0.5 (ll O/U + ll BTTS), sparowany bootstrap wzgledem championa (przyblizenie ze strzalow,
w_xg z konfiguracji). Warianty: prawdziwe xG przy w_xg 0.2 / 0.4 / 0.6. Kandydat ustalony przed uruchomieniem
na ligach innych niz E0: w_xg = 0.4 (wybrane na E0, wiec dla E0 to wynik in-sample).
Okno walidacji: 2023-07-01..2025-06-30 (sezon 2022/23 to rozgrzewka xG; wczesniej zrodlo nie ma xG).
Holdout (--holdout): mecze od 2025-07-01, tylko jesli pobrane. Brak xG w meczu = przyblizenie ze strzalow.
Uzycie: python backtest/statsapi/xg_real.py [--holdout] [LIGA ...]"""
import json
import sys
from dataclasses import replace

sys.path.insert(0, ".")

import pandas as pd  # noqa: E402

from typer.features.real_xg import attach as attach_real_xg, load_cached  # noqa: E402
from typer.metrics.scores import paired_diff_ci  # noqa: E402
from typer.pipeline.backtest import params_from_config  # noqa: E402
from typer.pipeline.data import load_matches  # noqa: E402
from typer.pipeline.engine import Engine  # noqa: E402
from typer.pipeline.goal_backtest import per_match_j  # noqa: E402

VAL = ("2023-07-01", "2025-06-30")
HOLD = ("2025-07-01", "2099-12-31")
WEIGHTS = (0.2, 0.4, 0.6)
CANDIDATE = "xg_prawdziwe_w0.4"
DIFFS: dict = {}            # liga -> wariant -> roznice J per mecz (do lacznego CI)


def attach(df: pd.DataFrame, lg: str):
    g = df[df["league"] == lg]
    xg = load_cached(lg)
    if xg.empty:
        return None, []
    return attach_real_xg(g, {lg: xg})


def evaluate(d: pd.DataFrame, window) -> dict:
    base = params_from_config()
    runs = {"champion_proxy": (d.drop(columns=["xg_h", "xg_a"]), base)}
    runs.update({f"xg_prawdziwe_w{w}": (d, replace(base, w_xg=w)) for w in WEIGHTS})
    J = {}
    for name, (x, p) in runs.items():
        out = Engine(p, collect_features=False).run(x, predict_from="2008-07-01")
        dt = pd.to_datetime(out["date"])
        out = out[(dt >= pd.Timestamp(window[0])) & (dt <= pd.Timestamp(window[1]))]
        J[name] = per_match_j(out)
    ref = J["champion_proxy"]
    if not len(ref):
        return {}
    DIFFS[d["league"].iloc[0]] = {k: (v.loc[ref.index] - ref).to_numpy() for k, v in J.items() if k != "champion_proxy"}
    return dict(n=int(len(ref)), J={k: float(v.mean()) for k, v in J.items()},
                roznica_vs_champion={k: paired_diff_ci((v.loc[ref.index] - ref).to_numpy())
                                     for k, v in J.items() if k != "champion_proxy"})


if __name__ == "__main__":
    args = sys.argv[1:]
    hold = "--holdout" in args
    leagues = [a for a in args if not a.startswith("--")] or ["E0", "D1", "F1", "I1", "SP1", "POL"]
    window = HOLD if hold else VAL
    df = load_matches()
    res = {"okno": window, "kandydat": CANDIDATE, "ligi": {}}
    for lg in leagues:
        d, pending = attach(df, lg)
        if d is None:
            print(lg, "brak danych TheStatsAPI", flush=True)
            continue
        dt = pd.to_datetime(d["date"])
        win = (dt >= pd.Timestamp(window[0])) & (dt <= pd.Timestamp(window[1])) & d["fthg"].notna()
        r = dict(pokrycie_xg_w_oknie=float(d.loc[win, "xg_h"].notna().mean()) if win.any() else 0.0,
                 niedopasowane=pending, **evaluate(d, window))
        res["ligi"][lg] = r
        c = r.get("roznica_vs_champion", {}).get(CANDIDATE)
        print(lg, "n", r.get("n"), "pokrycie", round(r["pokrycie_xg_w_oknie"], 3),
              "kandydat", c and round(c["mean"], 5), c and tuple(round(x, 5) for x in c["ci95"]), flush=True)
    import numpy as np
    for name, lgs in (("razem", list(DIFFS)), ("poza_E0_test_wagi", [x for x in DIFFS if x != "E0"])):
        if lgs:
            res[name] = {w: paired_diff_ci(np.concatenate([DIFFS[x][w] for x in lgs])) for w in DIFFS[lgs[0]]}
    tag = "holdout" if hold else "walidacja"
    json.dump(res, open(f"backtest/statsapi/xg_real_{tag}.json", "w"), indent=1, default=float)
    print(json.dumps({k: res.get(k) for k in ("razem", "poza_E0_test_wagi")}, indent=1, default=float))
