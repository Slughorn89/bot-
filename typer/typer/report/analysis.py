"""Analiza wynikow (sekcja 14): walidacja danych przed pokazaniem wniosku i korekta na
wielokrotne porownania. Liczby wylacznie z pliku predykcji i z JSON-a evaluate.py."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

Z90 = 1.6448536269514722  # kwantyl 0.95 rozkladu normalnego (CI90 w evaluate.py)


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def _norm_isf(p: float) -> float:
    """Odwrotnosc ogona rozkladu normalnego (bisekcja, bez scipy)."""
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _norm_sf(mid) > p else (lo, mid)
    return (lo + hi) / 2


def segment_significance(report: dict, alpha_one_sided: float = 0.05) -> list[dict]:
    """Segmenty z flaga 'slaby' po korekcie Bonferroniego.
    W evaluate.py segment jest 'slaby', gdy dolna granica CI90 luki do rynku > 0 (jednostronnie 5%).
    Przy m segmentach okolo m * 5% wyjdzie 'slabych' przypadkiem (sekcja 14.3), wiec przeliczamy:
    SE z szerokosci CI90, p jednostronne, prog alpha / m."""
    segs = [s for s in report.get("segmenty", []) if "luka_ci90" in s]
    m = len(segs)
    out = []
    for s in segs:
        lo, hi = s["luka_ci90"]
        se = max((hi - lo) / (2 * Z90), 1e-12)
        z = s["luka_vs_rynek"] / se
        p = _norm_sf(z)
        z_bonf = _norm_isf(alpha_one_sided / max(m, 1))
        key = {k: s[k] for k in ("sport", "league", "market") if k in s}
        out.append(dict(key, n=s["n"], luka=s["luka_vs_rynek"], ci90=(lo, hi), p_jednostronne=p,
                        slaby_bez_korekty=bool(s.get("slaby")), slaby_po_korekcie=bool(p < alpha_one_sided / max(m, 1)),
                        dolna_granica_po_korekcie=s["luka_vs_rynek"] - z_bonf * se, m=m))
    return sorted(out, key=lambda r: r["p_jednostronne"])


def validate_preds(preds: pd.DataFrame, fixtures: pd.DataFrame | None = None, segment_col: str = "league"
                   ) -> list[dict]:
    """Kontrole z sekcji 14.2 krok 4, zanim pokazesz wniosek. Zwraca liste (kontrola, status, info)."""
    res = []

    def add(name, ok, info, warn_only=False):
        res.append(dict(kontrola=name, status="ok" if ok else ("warn" if warn_only else "error"), info=info))

    ev = preds.groupby("event_id").first()
    if fixtures is not None and len(fixtures):
        missing = set(fixtures["event_id"]) - set(ev.index)
        add("rozliczenia_kompletne", not missing,
            f"{len(missing)} meczow z terminarza bez rozliczonej predykcji" if missing else "wszystkie mecze rozliczone")
    nulls = int(preds["outcome"].isna().sum())
    add("brak_nulli_outcome", nulls == 0, f"{nulls} pustych outcome")
    if "odds_close" in preds.columns:
        cov = preds["odds_close"].notna().mean()
        add("pokrycie_odds_close", cov >= 0.5, f"{cov:.0%} wierszy z kursem zamkniecia", warn_only=True)
    one = preds[preds["market"] == "1X2"]
    if len(one):
        p = one.groupby("event_id").apply(lambda g: g.loc[g["outcome"] == 1, "p_model"].sum() /
                                          max(g["p_model"].sum(), 1e-12), include_groups=False)
        ll = float(-np.log(np.clip(p, 1e-12, 1)).mean())
        add("zakres_log_loss_1x2", 0.90 <= ll <= 1.10, f"log loss 1X2 {ll:.4f} (oczekiwane ok. 0.95-1.05)",
            warn_only=True)
    d = pd.to_datetime(ev["date"]).sort_values()
    if len(d) > 1:
        gaps = d.diff().dt.days
        # przerwa letnia (koniec przerwy w czerwcu-sierpniu) jest normalna; reszta do wyjasnienia
        big = gaps[(gaps > 21) & ~d.dt.month.isin([6, 7, 8])]
        opis = ", ".join(f"{(t - pd.Timedelta(days=int(g))).date()}..{t.date()}" for t, g in zip(d[big.index], big))
        add("ciaglosc_czasu", big.empty, f"{len(big)} dziur > 21 dni poza latem: {opis} (przerwa w lidze czy "
            f"awaria pobierania?)" if len(big) else "brak dziur poza przerwa letnia", warn_only=True)
    if segment_col in preds.columns:
        tot = preds["event_id"].nunique()
        seg = preds.groupby(segment_col)["event_id"].nunique().sum()
        add("segmenty_sumuja_sie", seg == tot, f"suma segmentow {seg} vs calosc {tot}")
    return res
