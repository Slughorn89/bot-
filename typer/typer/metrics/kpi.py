"""KPI zakladow (modul 6). Glowny: CLV wzgledem kursu zamkniecia ostrego bukmachera. ROI tylko pomocniczo.

CLV zakladu = kurs_wziety * p_zamkniecia_bez_marzy - 1  (= kurs_wziety / uczciwy_kurs_zamkniecia - 1).
  * zamkniecie tylko ostre (Pinnacle: football-data PSC*, albo snapshot "close" z The Odds API dla pinnacle);
    brak ostrego zamkniecia = CLV "n/d", nigdy ciche zastepstwo miekkim bukmacherem,
  * marza zdejmowana metoda wybrana w module 6 (config/model.yaml: devig).
ROI = suma zysku / suma stawek, zawsze z CI90 i CI95 z bootstrapu (losowanie zakladow; jeden zaklad na mecz,
wiec zaklady sa w przyblizeniu niezalezne). Opcjonalny podatek od stawki (Polska: 12%).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from typer.betting.devig import devig_rows
from typer.metrics.scores import bootstrap_ci

SHARP_BOOKS = {"pinnacle"}


def clv(odds_taken, close_odds: np.ndarray, sel: np.ndarray, method: str = "shin") -> np.ndarray:
    """odds_taken (n,), close_odds (n, k) kursy zamkniecia CALEGO rynku, sel (n,) indeks wybranego wyniku."""
    P = devig_rows(close_odds, method)
    sel = np.asarray(sel, int)
    p = P[np.arange(len(sel)), sel]
    return np.asarray(odds_taken, float) * p - 1.0


def roi_stats(stake, profit, n_boot: int = 2000, seed: int = 7) -> dict:
    stake, profit = np.asarray(stake, float), np.asarray(profit, float)
    if len(stake) == 0:
        return dict(n=0, roi=None)
    ci = bootstrap_ci(lambda s, p: p.sum() / s.sum(), [stake, profit], n_boot, seed)
    return dict(n=int(len(stake)), obrot=float(stake.sum()), zysk=float(profit.sum()), roi=ci["wartosc"],
                roi_ci90=ci["ci90"], roi_ci95=ci["ci95"])


def clv_stats(c, n_boot: int = 2000, seed: int = 7) -> dict:
    c = np.asarray(c, float)
    c = c[np.isfinite(c)]
    if len(c) == 0:
        return dict(n=0, clv="n/d", powod="brak kursow zamkniecia ostrego bukmachera")
    ci = bootstrap_ci(lambda x: x.mean(), [c], n_boot, seed)
    return dict(n=int(len(c)), clv=ci["wartosc"], clv_ci90=ci["ci90"], clv_ci95=ci["ci95"],
                bije_zamkniecie=float((c > 0).mean()))


def settle_profit(odds, won, stake=1.0, tax_rate: float = 0.0, push=None) -> np.ndarray:
    """Zysk zakladu: wygrana (kurs * stawka * (1 - podatek) - stawka), przegrana -stawka, zwrot 0."""
    odds, won = np.asarray(odds, float), np.asarray(won, bool)
    stake = np.broadcast_to(np.asarray(stake, float), odds.shape)
    prof = np.where(won, odds * stake * (1 - tax_rate) - stake, -stake)
    if push is not None:
        prof = np.where(np.asarray(push, bool), 0.0, prof)
    return prof


def bet_report(bets: pd.DataFrame, n_boot: int = 2000) -> dict:
    """bets: kolumny stake, profit, opcjonalnie clv. CLV pierwszy, ROI pomocniczo."""
    if bets is None or len(bets) == 0:
        return dict(zaklady=0, kpi_glowny="CLV", clv=clv_stats([]), roi=roi_stats([], []))
    if bets["event_id"].duplicated().any():
        raise ValueError("wiecej niz jeden zaklad na mecz: CI z bootstrapu bylyby zanizone")
    c = bets["clv"] if "clv" in bets else pd.Series(np.nan, index=bets.index)
    return dict(zaklady=int(len(bets)), kpi_glowny="CLV", clv=clv_stats(c, n_boot),
                roi=roi_stats(bets["stake"], bets["profit"], n_boot))
