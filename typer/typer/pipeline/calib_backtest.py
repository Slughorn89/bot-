"""Modul 6: kalibracja i metryki na walidacji (2018/19 do 2024/25), krocząco per sezon.

Kroki:
  1. ramka ocen online (champion bez warstw) + zamkniecia Pinnacle (tylko do oceny),
  2. usuwanie marzy: proporcjonalna / Shin / potegowa na kursie wzietym (Bet365 sprzed meczu) i na
     zamknieciu Pinnacle; log loss, Brier, ECE zdjetego rynku wzgledem wynikow, per rynek i liga,
  3. kalibracja samego modelu: kandydaci per rynek i liga, wybor po ECE z bezpiecznikiem log loss,
  4. blend z rynkiem w chwili typu: waga per liga sciagana do globalnej (k z siatki), potem kalibracja
     wybrana na OOF mieszanki,
  5. porownanie z championem (online -> blend globalny -> vector/Platt): log loss, Brier, ECE, CI,
  6. KPI zakladow: CLV wzgledem zamkniecia Pinnacle (glowny), ROI z CI90/CI95 (pomocniczo),
  7. wykresy niezawodnosci per rynek i liga do reports/calibration/<okres>/.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from typer import config
from typer.betting.devig import METHODS, devig_rows
from typer.metrics.kpi import bet_report, clv, settle_profit
from typer.metrics.plots import reliability_plot
from typer.metrics.scores import brier, ece, log_loss, per_event_log_loss
from typer.models.calibration.select import MARKETS, calibrate_select_fn, market_arrays, select, uniform_choice
from typer.pipeline import layers as L

log = logging.getLogger("typer.m6")
REPORTS = config.ROOT / "reports" / "calibration"
CAL_RUNS = [("none", "none"), ("vector_L", "platt_L"), ("vector_G", "platt_G"), ("temperature_L", "isotonic_L"),
            ("temperature_G", "isotonic_G"), ("isotonic_L", None), ("isotonic_G", None)]


def _ci(d: np.ndarray, n_boot: int = 2000, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    m = d[rng.integers(0, len(d), (n_boot, len(d)))].mean(axis=1)
    return dict(srednia=float(d.mean()), ci90=tuple(np.percentile(m, [5, 95]).round(5)),
                ci95=tuple(np.percentile(m, [2.5, 97.5]).round(5)))


# ---------------- usuwanie marzy ----------------
ODDS = {"1X2": (["odds_h", "odds_d", "odds_a"], ["close_h", "close_d", "close_a"]),
        "OU2.5": (["odds_o25", "odds_u25"], ["close_o25", "close_u25"])}


def devig_comparison(fr: pd.DataFrame) -> pd.DataFrame:
    """Ktora metoda daje prawdopodobienstwa rynku najblizsze wynikom (na tych samych meczach)."""
    y = L.outcomes(fr)
    yk = {"1X2": y["1x2"], "OU2.5": 1 - y["over"]}       # kolumny O/U: [over, under] -> indeks 0 = over
    rows = []
    for market, (taken, close) in ODDS.items():
        for src, cols in (("wziety_b365", taken), ("zamkniecie_pinnacle", close)):
            O = fr[cols].to_numpy(float)
            Ps = {m: devig_rows(O, m) for m in METHODS}
            ok = np.all([np.isfinite(P).all(axis=1) for P in Ps.values()], axis=0)
            for lg in ["razem"] + sorted(fr["league"].unique()):
                sel = ok & ((fr["league"] == lg).to_numpy() if lg != "razem" else True)
                if sel.sum() < 200:
                    continue
                base = per_event_log_loss(Ps["proportional"][sel], yk[market][sel])
                for m, P in Ps.items():
                    ll = per_event_log_loss(P[sel], yk[market][sel])
                    r = dict(rynek=market, zrodlo=src, liga=lg, metoda=m, n=int(sel.sum()), log_loss=float(ll.mean()),
                             brier=brier(P[sel], yk[market][sel]), ece=ece(P[sel], yk[market][sel]))
                    if m != "proportional":
                        c = _ci(ll - base)
                        r.update(d_vs_prop=c["srednia"], ci95=c["ci95"])
                    rows.append(r)
    return pd.DataFrame(rows)


# ---------------- kalibracja ----------------
def calibration_oof(fr: pd.DataFrame, seasons: list[str], first: list | None = None) -> dict[str, pd.DataFrame]:
    """OOF kazdego kandydata (na wyjsciu warstw `first`, np. blendu)."""
    first = first or []
    oof = {}
    for c1, cb in CAL_RUNS:
        out = L.chain_oof(fr, seasons, first + [calibrate_select_fn(uniform_choice(c1, cb or "none"))])
        out = out.sort_values("event_id").reset_index(drop=True)
        oof[c1] = out
        if cb:
            oof[cb] = out
    return oof


def quality(df: pd.DataFrame) -> dict:
    out = {}
    for market in MARKETS:
        P, y = market_arrays(df, market)
        out[market] = dict(n=int(len(y)), log_loss=log_loss(P, y), brier=brier(P, y), ece=ece(P, y))
    out["J"] = out["1X2"]["log_loss"] + 0.5 * (out["OU2.5"]["log_loss"] + out["BTTS"]["log_loss"])
    return out


def per_match_j(df: pd.DataFrame) -> np.ndarray:
    j = np.zeros(len(df))
    for market, w in (("1X2", 1.0), ("OU2.5", 0.5), ("BTTS", 0.5)):
        P, y = market_arrays(df, market)
        j += w * per_event_log_loss(P, y)
    return j


def compare(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    a, b = a.sort_values("event_id"), b.sort_values("event_id")
    assert (a["event_id"].to_numpy() == b["event_id"].to_numpy()).all()
    out = {"J": _ci(per_match_j(b) - per_match_j(a))}
    for market in MARKETS:
        Pa, y = market_arrays(a, market)
        Pb, _ = market_arrays(b, market)
        out[market] = _ci(per_event_log_loss(Pb, y) - per_event_log_loss(Pa, y))
    return out


# ---------------- zaklady i KPI ----------------
SEL = {"1X2": [("1", "p_h", "odds_h", 0), ("X", "p_d", "odds_d", 1), ("2", "p_a", "odds_a", 2)],
       "OU2.5": [("over2.5", "p_over", "odds_o25", 0), ("under2.5", None, "odds_u25", 1)]}


def bets_from(df: pd.DataFrame, threshold: float, devig_close: dict, tax_rate: float = 0.0) -> pd.DataFrame:
    """Jeden zaklad na mecz: selekcja o najwiekszej przewadze p * kurs * (1 - podatek) - 1 >= prog, stawka 1."""
    y = L.outcomes(df)
    cands = []
    for market, sels in SEL.items():
        close = df[ODDS[market][1]].to_numpy(float)
        for sel, pcol, ocol, k in sels:
            p = df[pcol].to_numpy(float) if pcol else 1 - df["p_over"].to_numpy(float)
            o = df[ocol].to_numpy(float)
            won = (y["1x2"] == k) if market == "1X2" else ((y["over"] == 1) if k == 0 else (y["over"] == 0))
            c = clv(o, close, np.full(len(df), k), devig_close[market])
            cands.append(pd.DataFrame(dict(event_id=df["event_id"].to_numpy(), league=df["league"].to_numpy(),
                                           market=market, selection=sel, p=p, odds=o,
                                           edge=p * o * (1 - tax_rate) - 1, won=won, clv=c)))
    c = pd.concat(cands, ignore_index=True)
    c = c[np.isfinite(c["odds"]) & (c["edge"] >= threshold)]
    c = c.sort_values("edge", ascending=False).drop_duplicates("event_id")
    c["stake"] = 1.0
    c["profit"] = settle_profit(c["odds"], c["won"], 1.0, tax_rate)
    return c


def kpi(df: pd.DataFrame, threshold: float, devig_close: dict) -> dict:
    out = {}
    for tax in (0.0, 0.12):
        b = bets_from(df, threshold, devig_close, tax)
        r = bet_report(b)
        r["per_liga"] = {lg: dict(n=len(g), clv=bet_report(g)["clv"].get("clv"), roi=float(g["profit"].sum() / len(g)))
                         for lg, g in b.groupby("league")}
        out[f"podatek_{int(tax * 100)}"] = r
    return out


# ---------------- wykresy ----------------
def plots(df: pd.DataFrame, tag: str, label: str, before: pd.DataFrame | None = None) -> list[str]:
    out = []
    for market in MARKETS:
        for lg in ["razem"] + sorted(df["league"].unique()):
            d = df if lg == "razem" else df[df["league"] == lg]
            P, y = market_arrays(d, market)
            series = {}
            if before is not None:
                b = before if lg == "razem" else before[before["league"] == lg]
                Pb, yb = market_arrays(b, market)
            if market == "1X2":
                for j, name in enumerate(("1", "X", "2")):
                    series[f"{label} {name}"] = (P[:, j], (y == j).astype(float))
            else:
                series[label] = (P, y)
                if before is not None:
                    series["przed kalibracja"] = (Pb, yb)
            path = REPORTS / tag / f"{market.replace('.', '')}_{lg}.png"
            reliability_plot(series, path, title=f"{market} {lg} ({tag})")
            out.append(str(path.relative_to(config.ROOT)))
    return out
