"""Champion (oceny online) z prawdziwym xG (TheStatsAPI) zamiast przyblizenia ze strzalow, per liga.

Ocena: J = ll 1X2 + 0.5 (ll O/U + ll BTTS), sparowany bootstrap wzgledem championa (przyblizenie ze strzalow,
w_xg z konfiguracji). Warianty: prawdziwe xG przy w_xg 0.2 / 0.4 / 0.6. Kandydat ustalony przed uruchomieniem
na ligach innych niz E0: w_xg = 0.4 (wybrane na E0, wiec dla E0 to wynik in-sample).
Okno walidacji: 2023-07-01..2025-06-30 (sezon 2022/23 to rozgrzewka xG; wczesniej zrodlo nie ma xG).
Holdout (--holdout): mecze od 2025-07-01, tylko jesli pobrane. Brak xG w meczu = przyblizenie ze strzalow.
Uzycie: python backtest/statsapi/xg_real.py [--holdout] [LIGA ...]"""
import json
import pickle
import sys
from dataclasses import replace

sys.path.insert(0, ".")

import pandas as pd  # noqa: E402

from typer import config  # noqa: E402
from typer.entities.mapping import resolve_many  # noqa: E402
from typer.metrics.scores import paired_diff_ci  # noqa: E402
from typer.pipeline.backtest import params_from_config  # noqa: E402
from typer.pipeline.data import load_matches  # noqa: E402
from typer.pipeline.engine import Engine  # noqa: E402
from typer.pipeline.goal_backtest import per_match_j  # noqa: E402

VAL = ("2023-07-01", "2025-06-30")
HOLD = ("2025-07-01", "2099-12-31")
WEIGHTS = (0.2, 0.4, 0.6)
CANDIDATE = "xg_prawdziwe_w0.4"


def real_xg(lg: str) -> pd.DataFrame:
    parts = []
    for f in sorted(config.DATA_DIR.glob(f"thestatsapi_{lg}_*.pkl")):
        rec = pd.DataFrame(pickle.load(open(f, "rb")))
        st = rec[rec["_type"] == "TeamMatchStats"]
        if st.empty:
            continue
        k = ["home", "away", "kickoff_utc"]
        h = st[st["side"] == "home"][k + ["xg"]].rename(columns={"xg": "xg_h"})
        a = st[st["side"] == "away"][k + ["xg"]].rename(columns={"xg": "xg_a"})
        parts.append(h.merge(a, on=k).rename(columns={"home": "src_home", "away": "src_away"}))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def attach(df: pd.DataFrame, lg: str):
    g = df[df["league"] == lg]
    xg = real_xg(lg)
    if xg.empty:
        return None, []
    teams = sorted(set(g["home"]) | set(g["away"]))
    mp, pending = resolve_many(sorted(set(xg["src_home"]) | set(xg["src_away"])), teams)
    xg["home"], xg["away"] = xg["src_home"].map(mp), xg["src_away"].map(mp)
    xg["date"] = pd.to_datetime(xg["kickoff_utc"]).dt.date
    xg = xg.dropna(subset=["home", "away"])[["home", "away", "date", "xg_h", "xg_a"]]
    xg = xg.drop_duplicates(["home", "away", "date"])
    return g.merge(xg, on=["home", "away", "date"], how="left"), [m.raw for m in pending]


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
    # razem: sklejone roznice per mecz nie sa dostepne po agregacji, wiec srednia wazona n (bez CI)
    ok = {k: v for k, v in res["ligi"].items() if v.get("n")}
    if ok:
        res["razem_wazone_n"] = {w: sum(v["n"] * v["roznica_vs_champion"][w]["mean"] for v in ok.values())
                                 / sum(v["n"] for v in ok.values()) for w in next(iter(ok.values()))["roznica_vs_champion"]}
    tag = "holdout" if hold else "walidacja"
    json.dump(res, open(f"backtest/statsapi/xg_real_{tag}.json", "w"), indent=1, default=float)
    print(json.dumps(res.get("razem_wazone_n"), indent=1))
