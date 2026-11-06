"""Champion (oceny online) z prawdziwym xG (TheStatsAPI) zamiast przyblizenia ze strzalow, Premier League.
Ocena: J = ll 1X2 + 0.5 (ll O/U + ll BTTS) na meczach 2021-07-01..2025-06-30 (sezon 2020/21 to rozgrzewka xG),
sparowany bootstrap wzgledem championa (przyblizenie, w_xg z konfiguracji). Warianty: prawdziwe xG przy
w_xg 0.2 / 0.4 / 0.6. Uzycie: python backtest/statsapi/xg_real.py"""
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

START, END = "2021-07-01", "2025-06-30"


def real_xg() -> pd.DataFrame:
    parts = []
    for yr in ("2021", "2122", "2223", "2324", "2425"):
        rec = pd.DataFrame(pickle.load(open(config.DATA_DIR / f"thestatsapi_E0_{yr}.pkl", "rb")))
        st = rec[rec["_type"] == "TeamMatchStats"]
        k = ["home", "away", "kickoff_utc"]
        h = st[st["side"] == "home"][k + ["xg"]].rename(columns={"xg": "xg_h"})
        a = st[st["side"] == "away"][k + ["xg"]].rename(columns={"xg": "xg_a"})
        w = h.merge(a, on=k).rename(columns={"home": "src_home", "away": "src_away"})
        print(yr, "meczow", len(w), "z xG", int(w["xg_h"].notna().sum()), flush=True)
        parts.append(w)
    return pd.concat(parts, ignore_index=True)


df = load_matches()
xg = real_xg()
e0_teams = sorted(set(df.loc[df["league"] == "E0", "home"]) | set(df.loc[df["league"] == "E0", "away"]))
mp, pending = resolve_many(sorted(set(xg["src_home"]) | set(xg["src_away"])), e0_teams)
xg["home"], xg["away"] = xg["src_home"].map(mp), xg["src_away"].map(mp)
xg["date"] = pd.to_datetime(xg["kickoff_utc"]).dt.date
xg = xg.dropna(subset=["home", "away"])[["home", "away", "date", "xg_h", "xg_a"]]
e0 = df[df["league"] == "E0"].merge(xg, on=["home", "away", "date"], how="left")
cov = e0.loc[(pd.to_datetime(e0["date"]) >= pd.Timestamp("2020-08-01")), "xg_h"].notna().mean()

base = params_from_config()
runs = {"champion_proxy": (e0.drop(columns=["xg_h", "xg_a"]), base)}
for w in (0.2, 0.4, 0.6):
    runs[f"xg_prawdziwe_w{w}"] = (e0, replace(base, w_xg=w))
J = {}
for name, (d, p) in runs.items():
    out = Engine(p, collect_features=False).run(d, predict_from="2008-07-01")
    out = out[(pd.to_datetime(out["date"]) >= pd.Timestamp(START)) & (pd.to_datetime(out["date"]) <= pd.Timestamp(END))]
    J[name] = per_match_j(out)
    print(name, round(float(J[name].mean()), 5), flush=True)
ref = J["champion_proxy"]
res = dict(pokrycie_xg_od_2020=float(cov), niedopasowane=[m.raw for m in pending], n=int(len(ref)),
           J={k: float(v.mean()) for k, v in J.items()},
           roznica_vs_champion={k: paired_diff_ci((v.loc[ref.index] - ref).to_numpy()) for k, v in J.items()
                                if k != "champion_proxy"})
print(json.dumps(res, indent=1, default=float))
json.dump(res, open("backtest/statsapi/xg_real_E0.json", "w"), indent=1, default=float)
