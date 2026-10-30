from __future__ import annotations

import html
import re
import unicodedata

_TAG_RE = re.compile(r"<[^>]+>")


def fold(text: str) -> str:
    """Małe litery bez polskich znaków: 'Park Śląski' -> 'park slaski'."""
    text = (text or "").replace("ł", "l").replace("Ł", "L")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower())


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", text))).strip()


def date_patterns(day) -> list[re.Pattern]:
    """Wzorce wzmianek o dacie w tekście po fold()."""
    from .timeutil import PL_MONTHS_GENITIVE

    d, m, y = day.day, day.month, day.year
    month = PL_MONTHS_GENITIVE[m - 1]
    en = day.strftime("%B").lower()
    return [
        re.compile(rf"\b0?{d}[./-]0?{m}[./-](?:{y}|{y % 100})\b"),
        re.compile(rf"\b{y}-{m:02d}-{d:02d}\b"),
        re.compile(rf"\b0?{d}\s+{month}\b"),
        re.compile(rf"\b0?{d}\s+{en}\b|\b{en}\s+0?{d}\b"),
        re.compile(rf"\b0?{d}\.{m:02d}\b(?!\.\d)"),
    ]
