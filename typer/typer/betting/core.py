"""De-vig, przewaga, ulamkowy Kelly i limity ekspozycji (sekcja 10 skilla).

To narzedzie wspiera decyzje, nie gwarantuje zysku. Gra tylko u legalnych bukmacherow.
W Polsce legalni bukmacherzy pobieraja 12% podatku od stawki: ustaw tax_rate=0.12, zeby liczyc
przewage na kursie efektywnym (kurs * 0.88). Wtedy próg oplacalnosci jest duzo wyzej.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def devig(odds) -> np.ndarray:
    """Proporcjonalne zdjecie marzy: p_i = (1/o_i) / sum(1/o)."""
    inv = 1.0 / np.asarray(odds, dtype=float)
    return inv / inv.sum(axis=-1, keepdims=True)


def overround(odds) -> float:
    return float((1.0 / np.asarray(odds, dtype=float)).sum())


def edge(p: float, odds: float, tax_rate: float = 0.0) -> float:
    """Przewaga = p * kurs_efektywny - 1."""
    return p * odds * (1 - tax_rate) - 1


def kelly_fraction(p: float, odds: float, fraction: float = 0.25, tax_rate: float = 0.0) -> float:
    """f = fraction * (p*o - 1) / (o - 1), o = kurs efektywny; ujemne -> 0."""
    o = odds * (1 - tax_rate)
    if o <= 1:
        return 0.0
    return max(0.0, fraction * (p * o - 1) / (o - 1))


@dataclass
class Limits:
    max_per_bet: float = 0.02       # max 2% bankrolla na zaklad
    max_per_day: float = 0.10       # max 10% dziennie
    one_bet_per_match: bool = True  # zaklady w jednym meczu sa skorelowane
    drawdown_stop: float = 0.25     # spadek o 25% od szczytu = pauza i audyt


def select_and_stake(cands: list[dict], limits: Limits = Limits(), fraction: float = 0.25,
                     threshold: float = 0.05, tax_rate: float = 0.0,
                     bankroll: float = 1.0, peak: float = 1.0) -> list[dict]:
    """cands: dict(event_id, market, selection, p, odds, ...). Zwraca wybrane zaklady ze stawka
    (ulamek bankrolla). Respektuje limity; przy drawdownie >= stop nie stawia nic."""
    if peak > 0 and (peak - bankroll) / peak >= limits.drawdown_stop:
        return []
    scored = []
    for c in cands:
        e = edge(c["p"], c["odds"], tax_rate)
        if e >= threshold:
            f = min(kelly_fraction(c["p"], c["odds"], fraction, tax_rate), limits.max_per_bet)
            if f > 0:
                scored.append({**c, "edge": e, "stake_frac": f})
    scored.sort(key=lambda c: -c["edge"])
    out, used_events, day_total = [], set(), 0.0
    for c in scored:
        if limits.one_bet_per_match and c["event_id"] in used_events:
            continue
        room = limits.max_per_day - day_total
        if room <= 1e-9:
            break
        c["stake_frac"] = min(c["stake_frac"], room)
        out.append(c)
        used_events.add(c["event_id"])
        day_total += c["stake_frac"]
    return out
