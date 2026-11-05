"""Tokeny i formatowanie liczb (sekcja 13.1 skilla). JEDYNE miejsce z formatami w calym projekcie:
CLI, Telegram i HTML biora stad statusy i liczby, wiec mowia jednym jezykiem.

Regula: zadna metryka bez n, zadne ROI bez przedzialu. n < MIN_N = status.na + "za malo danych".
"""
from __future__ import annotations

import math

MIN_N = 100

STATUS = {
    "ok": dict(cli="[OK]", tg="✅ OK", label="OK", bg="#E6F4EA", fg="#1E7B34"),
    "warn": dict(cli="[UWAGA]", tg="⚠️ UWAGA", label="UWAGA", bg="#FEF3C7", fg="#92400E"),
    "error": dict(cli="[BLAD]", tg="⛔ BŁĄD", label="BŁĄD", bg="#FDE8E8", fg="#B42318"),
    "na": dict(cli="[--]", tg="➖ brak danych", label="brak danych", bg="#F2F4F7", fg="#475467"),
}
GATE_TO_STATUS = {"OK": "ok", "UWAGA": "warn", "BLAD": "error"}


def token(status: str, channel: str = "cli") -> str:
    return STATUS[status][channel]


def verdict_status(verdict: str | None) -> tuple[str, str]:
    """(status, tekst) dla werdyktu evaluate.py albo kodu wyjscia. Zly plik = error + kontrakt danych."""
    v = (verdict or "").upper()
    if "ZLY PLIK" in v or "KONTRAKT" in v:
        return "error", "zły plik (kontrakt danych)"
    if "NIEGOTOWY" in v:
        return "error", "NIEGOTOWY"
    if "GRY" in v and "TYLKO" not in v:
        return "ok", "GOTOWY do gry"
    if "TYLKO" in v:
        return "warn", "tylko typowanie"
    return "na", "brak werdyktu"


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def p(x) -> str:
    return f"{x:.2f}" if _ok(x) else "--"


def odds(x) -> str:
    return f"{x:.2f}" if _ok(x) else "--"


def ll(x) -> str:
    return f"{x:.4f}" if _ok(x) else "--"


def gap(x) -> str:
    return f"{x:+.4f}" if _ok(x) else "--"


def ece(x) -> str:
    return f"{x:.3f}" if _ok(x) else "--"


def pct(x) -> str:
    """CLV, ROI, przewaga: procent ze znakiem, 1 miejsce."""
    return f"{100 * x:+.1f}%" if _ok(x) else "--"


def stake(x) -> str:
    return f"{100 * x:.1f}%" if _ok(x) else "--"


def ci(lo, hi, kind: str = "pct") -> str:
    f = pct if kind == "pct" else gap
    return f"[{f(lo)}, {f(hi)}]" if _ok(lo) and _ok(hi) else "[--]"


def with_ci(x, lo, hi, kind: str = "pct") -> str:
    """Przedzial zawsze w nawiasie zaraz za wartoscia: '+3.5% [+3.1%, +3.9%]'."""
    f = pct if kind == "pct" else gap
    return f"{f(x)} {ci(lo, hi, kind)}"


def n(k) -> str:
    return f"n={int(k)}" if _ok(k) else "n=0"


def small_sample(k) -> bool:
    return not _ok(k) or int(k) < MIN_N
