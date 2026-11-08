"""Modul 6 na walidacji (2018/19 do 2024/25) i drugie spojrzenie na holdout. Wynik: backtest/calibration/m6.json,
wykresy: reports/calibration/<okres>/. Uruchomienie: python backtest/calibration/run_m6.py"""
import json
import logging
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from typer import config  # noqa: E402
from typer.models.calibration.select import calibrate_select_fn, select  # noqa: E402
from typer.pipeline import calib_backtest as M  # noqa: E402
from typer.pipeline import layers as L  # noqa: E402
from typer.pipeline.backtest import build_frame, seasons_between  # noqa: E402
from typer.pipeline.data import attach_closing, load_matches, split_dates  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("m6")
OUT = Path("backtest/calibration")
t0 = time.time()
sd = split_dates()
cache = OUT / "frame.pkl"
if cache.exists():
    fr = pd.read_pickle(cache)
else:
    fr = build_frame(load_matches())
    fr.to_pickle(cache)
fr = attach_closing(fr)
log.info("ramka %s, %.0f s", fr.shape, time.time() - t0)
val = seasons_between(fr, sd["walidacja_od"], sd["walidacja_do"])
hold = seasons_between(fr, sd["holdout_od"])
V = fr[fr["season"].isin(val)]
res = dict(sezony_walidacji=val, sezony_holdout=hold)

# 1. usuwanie marzy
dv = M.devig_comparison(V)
res["devig"] = dv.to_dict(orient="records")
tot = dv[dv["liga"] == "razem"]
best = {(r, z): g.sort_values("log_loss").iloc[0]["metoda"] for (r, z), g in tot.groupby(["rynek", "zrodlo"])}
dev_taken = {m: best[(m, "wziety_b365")] for m in ("1X2", "OU2.5")}
dev_close = {m: best[(m, "zamkniecie_pinnacle")] for m in ("1X2", "OU2.5")}
res["devig_wybor"] = dict(wziety=dev_taken, zamkniecie=dev_close)
log.info("devig: wziety %s, zamkniecie %s (%.0f s)", dev_taken, dev_close, time.time() - t0)

# 2. kalibracja samego modelu
oof_m = M.calibration_oof(fr, val)
choice_m, tab_m = select(oof_m)
choice_m0, _ = select(oof_m, guard="ci95")           # pierwsza wersja bezpiecznika (do porownania)
res["kalibracja_model"] = dict(wybor=choice_m, tabela=tab_m.to_dict(orient="records"))
log.info("kalibracja modelu: %s (%.0f s)", choice_m, time.time() - t0)

# 3. blend per liga: siatka k (jedna metoda marzy dla obu rynkow blendu wg 1X2)
dm = dev_taken["1X2"]
grid = {}
for k in (0.0, 300.0, 1000.0, float("inf")):
    b = L.chain_oof(fr, val, [L.blend_fn(per_league=True, shrink_k=k, devig_method=dm)])
    grid[k] = float(M.per_match_j(b).mean())
    log.info("blend k=%s J=%.5f", k, grid[k])
k_best = min(grid, key=grid.get)
res["blend_siatka_k"] = {str(k): v for k, v in grid.items()}
blend = L.blend_fn(per_league=True, shrink_k=k_best, devig_method=dm)
oof_b = M.calibration_oof(fr, val, first=[blend])
choice_b, tab_b = select(oof_b)
choice_b0, _ = select(oof_b, guard="ci95")
res["wybor_bezpiecznik_ci95"] = dict(model=choice_m0, po_blendzie=choice_b0)
res["kalibracja_po_blendzie"] = dict(wybor=choice_b, tabela=tab_b.to_dict(orient="records"))

# 4. lancuchy na walidacji
champ = L.chain_oof(fr, val, [L.blend_fn(), L.calibrate_fn("vector", "platt")])
model_cal = L.chain_oof(fr, val, [calibrate_select_fn(choice_m)])
raw = fr[fr["season"].isin(val)]
blend_only = L.chain_oof(fr, val, [blend])
m6 = L.chain_oof(fr, val, [blend, calibrate_select_fn(choice_b)])
m6_ci95 = L.chain_oof(fr, val, [blend, calibrate_select_fn(choice_b0)])
chains = dict(online=raw, online_kal_wybrana=model_cal, champion=champ, blend_per_liga=blend_only, m6=m6,
              m6_bezpiecznik_ci95=m6_ci95)
res["jakosc_walidacja"] = {k: M.quality(v) for k, v in chains.items()}
res["m6_vs_champion"] = M.compare(champ, m6)
res["m6_ci95_vs_champion"] = M.compare(champ, m6_ci95)
res["kal_vs_online"] = M.compare(raw, model_cal)
res["w_modelu_per_liga"] = blend_only.groupby("league")[["w_model_1x2", "w_model_ou"]].mean().round(3).to_dict()
thr = config.model_params().get("value_threshold", 0.05)
res["kpi_walidacja"] = {k: M.kpi(v, thr, dev_close) for k, v in (("champion", champ), ("m6", m6),
                                                                  ("model_bez_rynku", model_cal))}
res["wykresy"] = M.plots(m6, "walidacja_m6", "m6", before=blend_only) + M.plots(raw, "walidacja_online", "online")
log.info("walidacja gotowa (%.0f s)", time.time() - t0)

# 5. holdout: drugie spojrzenie (holdout championa zuzyty 2026-10-31), parametry zamrozone z walidacji
if hold:
    champ_h = L.chain_oof(fr, hold, [L.blend_fn(), L.calibrate_fn("vector", "platt")])
    m6_h = L.chain_oof(fr, hold, [blend, calibrate_select_fn(choice_b)])
    model_h = L.chain_oof(fr, hold, [calibrate_select_fn(choice_m)])
    res["jakosc_holdout"] = {"champion": M.quality(champ_h), "m6": M.quality(m6_h)}
    res["m6_vs_champion_holdout"] = M.compare(champ_h, m6_h)
    res["kpi_holdout"] = {k: M.kpi(v, thr, dev_close) for k, v in (("champion", champ_h), ("m6", m6_h),
                                                                    ("model_bez_rynku", model_h))}
    res["wykresy"] += M.plots(m6_h, "holdout_m6", "m6")
res["k_best"] = k_best
res["sekundy"] = round(time.time() - t0)
json.dump(res, open(OUT / "m6.json", "w", encoding="utf-8"), indent=1, default=lambda o: o if not isinstance(o, (np.floating, np.integer)) else o.item())
log.info("koniec (%.0f s)", time.time() - t0)
