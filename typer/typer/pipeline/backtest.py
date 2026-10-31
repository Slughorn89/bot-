"""Backtest: oceny online -> warstwy (kroczaco) -> plik predykcji (Zalacznik B) -> evaluate.py.

Dwa pliki, bo w danych z GitHuba nie ma kursow zamkniecia:
  preds.csv         odds_taken = Bet365 sprzed meczu (to, co dalo sie wziac). Bez odds_close:
                    evaluate.py oceni kalibracje, baseline i ROI, ale CLV nie policzy (uczciwie).
  preds_market.csv  odds_close = ten sam rynek sprzed meczu (dla POL kurs o nieznanym momencie),
                    bez odds_taken. Sluzy WYLACZNIE do porownania log loss z rynkiem i bramki
                    brak_wycieku. Gdy podlaczysz football-data.co.uk, w odds_close trafi prawdziwe
                    zamkniecie Pinnacle i bramka clv_dodatni zacznie dzialac.
Holdout (od split.holdout_od) uruchamiasz RAZ: po uzyciu zostaje znacznik backtest/HOLDOUT_USED.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from typer import config
from typer.pipeline import layers as L
from typer.pipeline.data import load_matches, split_dates
from typer.pipeline.engine import Engine
from typer.models.scores.online_poisson import Params

log = logging.getLogger("typer.backtest")
BT_DIR = config.ROOT / "backtest"
EVALUATE = config.ROOT / "tools" / "evaluate.py"


def params_from_config() -> Params:
    p = config.model_params().get("online_poisson", {})
    return Params(**p) if p else Params()


def seasons_between(df: pd.DataFrame, start, end=None) -> list[str]:
    out = []
    for s in sorted(df["season"].unique()):
        cut = L.season_cut(s)
        if cut >= pd.Timestamp(start) - pd.Timedelta(days=1) and (end is None or cut <= pd.Timestamp(end)):
            out.append(s)
    return out


LAYER_SETS = {
    "online": [],
    "online+cal": [L.calibrate_fn("vector", "platt")],
    "online+cal_iso": [L.calibrate_fn("isotonic", "isotonic")],
    "online+cal_temp": [L.calibrate_fn("temperature", "platt")],
    "gbm+cal": [L.gbm_fn(), L.calibrate_fn("vector", "platt")],
    "online+blend": [L.blend_fn()],
    "online+cal+blend": [L.calibrate_fn("vector", "platt"), L.blend_fn()],
    "online+blend+cal": [L.blend_fn(), L.calibrate_fn("vector", "platt")],
    "gbm+cal+blend": [L.gbm_fn(), L.calibrate_fn("vector", "platt"), L.blend_fn()],
}


def build_frame(df: pd.DataFrame | None = None, params: Params | None = None,
                predict_from: str = "2008-07-01") -> pd.DataFrame:
    df = df if df is not None else load_matches()
    eng = Engine(params or params_from_config(), collect_features=True)
    return eng.run(df, predict_from=predict_from)


def apply_layers(frame: pd.DataFrame, layer_set: str, seasons: list[str]) -> pd.DataFrame:
    fns = LAYER_SETS[layer_set]
    if not fns:
        return frame[frame["season"].isin(seasons)].copy()
    return L.chain_oof(frame, seasons, fns)


def to_preds(fr: pd.DataFrame, model_version: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Ramka meczowa -> wiersze selekcji (Zalacznik B)."""
    y = L.outcomes(fr)
    rows, mrows = [], []
    base = dict(sport="football", model_version=model_version)
    for i, r in enumerate(fr.itertuples(index=False)):
        common = dict(base, event_id=r.event_id, date=str(r.date), league=r.league)
        p1 = np.array([r.p_h, r.p_d, r.p_a], float)
        p1 = p1 / p1.sum()
        b1 = np.array([r.base_h, r.base_d, r.base_a])
        taken1 = [r.odds_h, r.odds_d, r.odds_a]
        bench1 = [r.bench_h, r.bench_d, r.bench_a]
        mkt1 = taken1 if np.isfinite(taken1).all() else bench1
        for k, sel in enumerate(("1", "X", "2")):
            out = int(y["1x2"][i] == k)
            rows.append(dict(common, market="1X2", selection=sel, p_model=p1[k], outcome=out,
                             p_baseline=b1[k], odds_taken=taken1[k]))
            mrows.append(dict(common, market="1X2", selection=sel, p_model=p1[k], outcome=out,
                              p_baseline=b1[k], odds_close=mkt1[k]))
        po, ov = float(r.p_over), int(y["over"][i])
        for sel, p, b, o, oc in (("over2.5", po, r.base_over, ov, r.odds_o25),
                                 ("under2.5", 1 - po, 1 - r.base_over, 1 - ov, r.odds_u25)):
            rows.append(dict(common, market="OU2.5", selection=sel, p_model=p, outcome=o,
                             p_baseline=b, odds_taken=oc))
            mrows.append(dict(common, market="OU2.5", selection=sel, p_model=p, outcome=o,
                              p_baseline=b, odds_close=oc))
        pb, bt = float(r.p_btts), int(y["btts"][i])
        for sel, p, b, o in (("yes", pb, r.base_btts, bt), ("no", 1 - pb, 1 - r.base_btts, 1 - bt)):
            rows.append(dict(common, market="BTTS", selection=sel, p_model=p, outcome=o, p_baseline=b,
                             odds_taken=np.nan))
            mrows.append(dict(common, market="BTTS", selection=sel, p_model=p, outcome=o, p_baseline=b,
                              odds_close=np.nan))
    preds = pd.DataFrame(rows)
    mkt = pd.DataFrame(mrows)
    # benchmark rynku tylko dla rynkow, w ktorych mamy kurs: inaczej evaluate pominie ll_market
    mkt = mkt[mkt["odds_close"].notna()]
    return preds, mkt


def run_evaluate(csv: Path, *, since=None, until=None, value_threshold=None, by="sport,league,market",
                 json_out: Path | None = None) -> tuple[int, str]:
    cmd = [sys.executable, str(EVALUATE), str(csv), "--by", by]
    if since:
        cmd += ["--since", str(since)]
    if until:
        cmd += ["--until", str(until)]
    if value_threshold is not None:
        cmd += ["--value-threshold", str(value_threshold)]
    if json_out:
        cmd += ["--json", str(json_out)]
    g = config.gates().get("gates", {})
    for k, v in g.items():
        cmd += [f"--{k.replace('_', '-')}", str(v)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + (p.stderr if p.returncode not in (0, 1, 2) else "")


def holdout_marker() -> Path:
    return BT_DIR / "HOLDOUT_USED"


def run(layer_set: str = "online+cal", holdout: bool = False, force_holdout: bool = False,
        model_version: str | None = None, frame: pd.DataFrame | None = None) -> dict:
    BT_DIR.mkdir(exist_ok=True)
    sd = split_dates()
    df = load_matches()
    frame = frame if frame is not None else build_frame(df)
    if holdout:
        if holdout_marker().exists() and not force_holdout:
            raise SystemExit(f"Holdout juz uzyty ({holdout_marker().read_text().strip()}). Strojenie na nim "
                             f"go spala: potrzebny nowy okres albo --force-holdout ze swiadomoscia skutkow.")
        start, end = sd["holdout_od"], None
    else:
        start, end = sd["walidacja_od"], sd["walidacja_do"]
    seasons = seasons_between(frame, start, end)
    fr = apply_layers(frame, layer_set, seasons)
    d = pd.to_datetime(fr["date"])
    fr = fr[(d >= pd.Timestamp(start)) & ((d <= pd.Timestamp(end)) if end else True)]
    mv = model_version or f"op-{layer_set}"
    preds, mkt = to_preds(fr, mv)
    tag = "holdout" if holdout else "valid"
    p_csv, m_csv = BT_DIR / f"preds_{tag}.csv", BT_DIR / f"preds_market_{tag}.csv"
    preds.to_csv(p_csv, index=False)
    mkt.to_csv(m_csv, index=False)
    vt = config.gates().get("value_threshold", 0.05)
    code_p, rep_p = run_evaluate(p_csv, value_threshold=vt, json_out=BT_DIR / f"report_{tag}.json")
    code_m, rep_m = run_evaluate(m_csv, json_out=BT_DIR / f"report_market_{tag}.json")
    (BT_DIR / f"report_{tag}.txt").write_text(rep_p)
    (BT_DIR / f"report_market_{tag}.txt").write_text(rep_m)
    if holdout:
        holdout_marker().write_text(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC, model {mv}\n")
    return dict(tag=tag, layer_set=layer_set, code_preds=code_p, code_market=code_m,
                metrics=L.metrics(fr), report_preds=rep_p, report_market=rep_m,
                preds_csv=str(p_csv), market_csv=str(m_csv))


def combined_verdict(code_preds: int, code_market: int) -> str:
    """Oba pliki musza przejsc twarde bramki. CLV wymaga kursow zamkniecia (football-data.co.uk)."""
    if code_preds == 2 or code_market == 2:
        return "NIEGOTOWY"
    if code_preds == 0 and code_market in (0, 1):
        return "GOTOWY do typowania i gry (CLV potwierdzony)"
    return "GOTOWY tylko do typowania (brak dowodu przewagi nad rynkiem)"
