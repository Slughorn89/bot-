"""Strojenie modelu rożnych (wersja A, bez stanu gry) na walidacji: half-life x ridge x cechy stylu.
Wybor po log loss rozkladu lacznego (metryka glowna). Wynik: backtest/corners/grid.json."""
import itertools
import json
import sys
import time

sys.path.insert(0, ".")

from typer.pipeline.corner_backtest import VARIANTS, run  # noqa: E402
from typer.pipeline.data import load_matches, split_dates  # noqa: E402

sd = split_dates()
df = load_matches(extended=True)
out = []
for hl, ridge, style in itertools.product([180, 365, 730], [3.0, 10.0, 30.0], [False, True]):
    t = time.time()
    res = run(df, sd["walidacja_od"], sd["walidacja_do"], workers=4, half_life=hl, ridge=ridge,
              use_style=style, variants={"A": VARIANTS["A"]})
    row = dict(half_life=hl, ridge=ridge, style=style, n=len(res),
               **{m: round(float(res[m].mean()), 5) for m in ["ll_joint", "ll_total", "ll_ou95", "ll_home45",
                                                               "ll_away45", "ll_hcp15", "ll_most"]},
               sek=round(time.time() - t))
    print(row, flush=True)
    out.append(row)
    json.dump(out, open("backtest/corners/grid.json", "w"), indent=1)
