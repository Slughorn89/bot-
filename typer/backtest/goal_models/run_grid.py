"""Siatka strojenia modelu goli na walidacji (2018-07-01..2025-06-30). Wynik: grid.json + ramki .pkl."""
import itertools, json, logging, time, sys
sys.path.insert(0, ".")
import pandas as pd
from typer.pipeline.data import load_matches
from typer.pipeline.goal_backtest import run
from typer.pipeline.layers import metrics
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
df = load_matches()
res = []
for hl, wx in itertools.product([120, 240, 480, 960], [0.0, 0.2, 0.4]):
    t = time.time()
    out = run(df, "2018-07-01", "2025-06-30", hl, wx, workers=4)
    out.to_pickle(f"backtest/goal_models/hl{hl}_wx{wx}.pkl")
    for v, g in out.groupby("variant"):
        m = metrics(g)
        res.append(dict(half_life=hl, w_xg=wx, variant=v, n=int(m["n"]), ll_1x2=m["ll_1x2"], ll_ou=m["ll_ou"],
                        ll_btts=m["ll_btts"], J=m["ll_1x2"] + 0.5 * (m["ll_ou"] + m["ll_btts"])))
    logging.info("hl=%d wx=%.1f gotowe w %.0fs: %s", hl, wx, time.time() - t,
                 {r["variant"]: round(r["J"], 5) for r in res[-3:]})
    json.dump(res, open("backtest/goal_models/grid.json", "w", encoding="utf-8"), indent=1)
print("KONIEC")
