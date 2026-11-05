"""Porownanie wersji modelu rożnych: baseline / A0 / A / B na walidacji (i raz na holdoucie z --holdout).
Parametry z config/model.yaml (corner_models). Wynik: backtest/corners/compare_<okres>.json
(tabele roznic log loss z CI90 i CI95, gamma w czasie, kalibracja srednich)."""
import json
import sys
import time

sys.path.insert(0, ".")

import pandas as pd  # noqa: E402

from typer import config  # noqa: E402
from typer.pipeline.corner_backtest import calibration_total, compare, run  # noqa: E402
from typer.pipeline.data import load_matches, split_dates  # noqa: E402

holdout = "--holdout" in sys.argv
sd = split_dates()
cc = config.model_params().get("corner_models", {})
start, end = (sd["holdout_od"], "2100-01-01") if holdout else (sd["walidacja_od"], sd["walidacja_do"])
tag = "holdout" if holdout else "walidacja"
t = time.time()
res = run(load_matches(extended=True), start, end, workers=4, half_life=cc.get("half_life", 365),
          ridge=cc.get("ridge", 3.0), use_style=cc.get("use_style", False), n_sims=cc.get("n_sims", 20000))
res.to_pickle(f"backtest/corners/res_{tag}.pkl")
llc = [c for c in res.columns if c.startswith("ll_")]
out = dict(okres=tag, od=str(start), do=str(end), params=cc, sekundy=round(time.time() - t),
           srednie=res.groupby("variant")[llc].mean().round(5).to_dict(orient="index"),
           porownania={f"{b}-{a}": compare(res, a, b, by_league=True).to_dict(orient="records")
                       for a, b in (("A", "B"), ("A0", "A"), ("baseline", "A"), ("baseline", "B"))})
b = res[res["variant"] == "B"].copy()
b["rok"] = pd.to_datetime(b["date"]).dt.year
out["gamma"] = b.groupby(["league", "rok"])[["g_trail", "g_lead", "r", "sigma"]].mean().round(3).reset_index(
).to_dict(orient="records")
out["kalibracja_sumy"] = {v: calibration_total(res, v).reset_index().to_dict(orient="records") for v in ("A", "B")}
json.dump(out, open(f"backtest/corners/compare_{tag}.json", "w"), indent=1, default=str)
print(json.dumps(out["srednie"], indent=1))
print(pd.DataFrame(out["porownania"]["B-A"]).to_string(index=False))
