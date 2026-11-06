"""Modul 3, jedna zmiana: wersja A + przewaga z kursu sprzed meczu (log p_gosp/p_gosc, Bet365 bez marzy)
jako cecha rożnych (gospodarz +s, gosc -s). Walidacja 2018-07..2025-06. Wynik: supremacy_walidacja.json"""
import json
import sys

sys.path.insert(0, ".")

from typer import config  # noqa: E402
from typer.pipeline.corner_backtest import VARIANTS, compare, run  # noqa: E402
from typer.pipeline.data import load_matches, split_dates  # noqa: E402

sd = split_dates()
cc = config.model_params()["corner_models"]
var = {"A": VARIANTS["A"], "A_przewaga": dict(frailty=True, state=False, supremacy=True)}
res = run(load_matches(extended=True), sd["walidacja_od"], sd["walidacja_do"], workers=4, half_life=cc["half_life"],
          ridge=cc["ridge"], use_style=cc["use_style"], variants=var, n_sims=1000)
out = dict(n=int(res["event_id"].nunique()),
           srednie=res.groupby("variant")[[c for c in res.columns if c.startswith("ll_")]].mean().round(5).to_dict("index"),
           A_przewaga_minus_A=compare(res, "A", "A_przewaga", by_league=True).to_dict("records"))
print(json.dumps(out["srednie"], indent=1))
for r in out["A_przewaga_minus_A"]:
    if r["liga"] == "razem" or r["rynek"] == "ll_joint":
        print(r["liga"], r["rynek"], r["roznica"], r["ci95"])
json.dump(out, open("backtest/corners/supremacy_walidacja.json", "w"), indent=1, default=str)
