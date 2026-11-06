"""Modul 3, jedna zmiana: wersja B z gamma ustalonym z minut zdarzen (state_effect.py, wariant z buforem)
vs A, na Premier League 2018/19..2023/24 (bez 2024/25, na ktorym gamma oszacowano). Wynik: b_causal_E0.json"""
import json
import sys

sys.path.insert(0, ".")

from typer import config  # noqa: E402
from typer.pipeline.corner_backtest import VARIANTS, compare, run_league  # noqa: E402
from typer.pipeline.data import load_matches  # noqa: E402

se = json.load(open("backtest/statsapi/state_effect_E0_2425.json"))["bufor_5min_przed_golem"]
g = (se["g_trail"], se["g_lead"])
cc = config.model_params()["corner_models"]
df = load_matches(extended=True)
var = {"A": VARIANTS["A"], "B": VARIANTS["B"], "B_przyczynowe": dict(frailty=True, state=True, fixed_gamma=g)}
res = run_league(df[df["league"] == "E0"], "2018-07-01", "2024-06-30", half_life=cc["half_life"], ridge=cc["ridge"],
                 use_style=cc["use_style"], variants=var, n_sims=cc.get("n_sims", 20000))
out = dict(gamma=dict(g_trail=g[0], g_lead=g[1]), n=int(res["event_id"].nunique()),
           srednie=res.groupby("variant")[[c for c in res.columns if c.startswith("ll_")]].mean().round(5).to_dict("index"),
           B_przyczynowe_minus_A=compare(res, "A", "B_przyczynowe", by_league=False).to_dict("records"),
           B_minus_A=compare(res, "A", "B", by_league=False).to_dict("records"))
print(json.dumps(out, indent=1, default=str))
json.dump(out, open("backtest/statsapi/b_causal_E0.json", "w"), indent=1, default=str)
