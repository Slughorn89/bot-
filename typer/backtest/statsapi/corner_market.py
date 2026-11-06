"""Model rożnych (modul 3, wersja A) vs rynek: kurs zamkniecia Bet365 na sumie rożnych (TheStatsAPI).
Log loss O/U na linii bukmachera, na tych samych meczach; marza zdjeta metoda z config (devig.zamkniecie OU2.5).
Uzycie: python backtest/statsapi/corner_market.py E0 2425 2024-08-01 2025-06-30"""
import json
import pickle
import sys

sys.path.insert(0, ".")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from typer import config  # noqa: E402
from typer.betting.devig import devig_rows  # noqa: E402
from typer.entities.mapping import resolve_many  # noqa: E402
from typer.metrics.scores import paired_diff_ci  # noqa: E402
from typer.pipeline.corner_backtest import VARIANTS, run_league  # noqa: E402
from typer.pipeline.data import load_matches  # noqa: E402

lg, yr, start, end = sys.argv[1:5]
VAR = sys.argv[5] if len(sys.argv) > 5 else "A"
cc = config.model_params()["corner_models"]
df = load_matches(extended=True)
res = run_league(df[df["league"] == lg], start, end, half_life=cc["half_life"], ridge=cc["ridge"],
                 use_style=cc["use_style"], variants={VAR: dict(VARIANTS["A"], supremacy=VAR == "A_przewaga")}, n_sims=1000)
recs = pd.DataFrame(pickle.load(open(config.DATA_DIR / f"thestatsapi_{lg}_{yr}.pkl", "rb")))
q = recs[(recs["_type"] == "OddsQuote") & (recs["kind"] == "close") & recs["market"].str.startswith("CORNERS")]
q = q[q["bookmaker"] == "bet365"].copy()
q["side"] = np.where(q["selection"].str.startswith("over"), "over", "under")
w = q.pivot_table(index=["home", "away", "kickoff_utc", "line"], columns="side", values="price").dropna().reset_index()
# nazwy TheStatsAPI -> nazwy football-data (kanoniczne w projekcie)
cands = sorted(set(res["home"]) | set(res["away"]))
mp, pending = resolve_many(sorted(set(w["home"]) | set(w["away"])), cands)
w["home"], w["away"] = w["home"].map(mp), w["away"].map(mp)       # niepewne -> NaN, mecz odpada (nie zgadujemy)
w["date"] = pd.to_datetime(w["kickoff_utc"]).dt.date
res["date"] = pd.to_datetime(res["date"]).dt.date
m = w.merge(res, on=["home", "away", "date"], how="inner")
meth = (config.model_params().get("devig") or {}).get("zamkniecie", {}).get("OU2.5", "power")
pm = devig_rows(m[["over", "under"]].to_numpy(float), meth)[:, 0]
pmod = np.array([r[f"p_over_{ln:g}"] if f"p_over_{ln:g}" in r else np.nan for ln, (_, r) in zip(m["line"], m.iterrows())])
y = ((m["hc"] + m["ac"]) > m["line"]).to_numpy(float)
ok = np.isfinite(pmod) & np.isfinite(pm)
eps = 1e-12
ll = lambda p: -(y[ok] * np.log(np.clip(p[ok], eps, 1)) + (1 - y[ok]) * np.log(np.clip(1 - p[ok], eps, 1)))
llm, llk = ll(pmod), ll(pm)
ci = paired_diff_ci(llm - llk)
out = dict(wariant=VAR, liga=lg, sezon=yr, mecze_z_kursem=int(len(w)), dopasowane=int(len(m)), ocenione=int(ok.sum()),
           niedopasowane_nazwy=sorted(m_.raw for m_ in pending),
           linie=m["line"].value_counts().to_dict(), metoda_marzy=meth,
           ll_model=float(llm.mean()), ll_rynek=float(llk.mean()), roznica_model_minus_rynek=ci["mean"],
           ci95=ci["ci95"], ece_model=None)
from typer.metrics.scores import ece  # noqa: E402
out["ece_model"], out["ece_rynek"] = ece(pmod[ok], y[ok]), ece(pm[ok], y[ok])
print(json.dumps(out, indent=1, default=float))
json.dump(out, open(f"backtest/statsapi/corner_market_{lg}_{yr}_{VAR}.json", "w"), indent=1, default=float)
