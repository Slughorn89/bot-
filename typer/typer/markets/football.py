"""Z macierzy wynikow -> prawdopodobienstwa rynkow. Wszystkie rynki z jednej macierzy,
wiec sa ze soba spojne: 1X2 sumuje sie do 1, O/U jest monotoniczne po liniach, handicapy
zgadzaja sie z rozkladem roznicy bramek.
"""
from __future__ import annotations

import numpy as np


def total_dist(m: np.ndarray) -> np.ndarray:
    """Rozklad sumy goli."""
    n = m.shape[0]
    out = np.zeros(2 * n - 1)
    for i in range(n):
        out[i:i + n] += m[i]
    return out


def margin_dist(m: np.ndarray) -> dict[int, float]:
    """Rozklad roznicy bramek (gospodarz - gosc)."""
    n = m.shape[0]
    out: dict[int, float] = {}
    for i in range(n):
        for j in range(n):
            out[i - j] = out.get(i - j, 0.0) + float(m[i, j])
    return out


def p_1x2(m: np.ndarray) -> dict[str, float]:
    h = float(np.tril(m, -1).sum())
    d = float(np.trace(m))
    return {"1": h, "X": d, "2": float(m.sum()) - h - d}


def p_ou(m: np.ndarray, line: float) -> dict[str, float]:
    """Over/under dla dowolnej linii; dla linii calkowitej zwraca tez zwrot (push)."""
    t = total_dist(m)
    goals = np.arange(len(t))
    over = float(t[goals > line].sum())
    under = float(t[goals < line].sum())
    out = {f"over{line:g}": over, f"under{line:g}": under}
    push = 1.0 - over - under
    if push > 1e-12:
        out["push"] = push
    return out


def p_btts(m: np.ndarray) -> dict[str, float]:
    yes = float(1 - m[0, :].sum() - m[:, 0].sum() + m[0, 0])
    return {"yes": yes, "no": 1 - yes}


def ah_probs(m: np.ndarray, line: float) -> dict[str, float]:
    """Handicap azjatycki dla gospodarza z linia polowkowa lub calkowita: win/push/lose.
    (Linie cwiartkowe obsluguje ah_expected_profit, dzielac stawke na dwie linie.)"""
    if (line * 4) % 2 != 0:
        raise ValueError("linia cwiartkowa: uzyj ah_expected_profit")
    win = push = 0.0
    for d, p in margin_dist(m).items():
        x = d + line
        if x > 1e-9:
            win += p
        elif abs(x) <= 1e-9:
            push += p
    return {"win": win, "push": push, "lose": 1 - win - push}


def ah_expected_profit(m: np.ndarray, line: float, odds: float, side: str = "home") -> float:
    """Oczekiwany zysk na 1 j. stawki dla dowolnej linii AH (takze cwiartkowej, np. -0.75)."""
    if side == "away":
        m = m.T
    lines = [line] if (line * 4) % 2 == 0 else [line - 0.25, line + 0.25]
    ev = 0.0
    for ln in lines:
        p = ah_probs(m, ln)
        ev += (p["win"] * (odds - 1) - p["lose"]) / len(lines)
    return ev


def all_markets(m: np.ndarray, ou_lines=(1.5, 2.5, 3.5)) -> dict[str, dict[str, float]]:
    out = {"1X2": p_1x2(m), "BTTS": p_btts(m)}
    for ln in ou_lines:
        out[f"OU{ln:g}"] = {k: v for k, v in p_ou(m, ln).items() if k != "push"}
    return out
