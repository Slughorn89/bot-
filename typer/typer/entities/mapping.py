"""Mapowanie nazw druzyn miedzy zrodlami ("Man Utd" vs "Manchester United").

Nazwa kanoniczna = nazwa z football-data.co.uk (glowne zrodlo historii).
Kolejnosc: reczne mapowanie -> alias ze slownika -> dopasowanie rozmyte.
Dopasowanie pewne (>= AUTO) i jednoznaczne przechodzi automatycznie, ale jest zapisane.
Niepewne trafia do kolejki 'pending' i mecz NIE jest typowany, dopoki czlowiek nie zdecyduje.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

AUTO = 0.90      # pewne dopasowanie
REVIEW = 0.60    # ponizej tego nawet nie proponujemy kandydata

# Znane rozjazdy nazw (The Odds API / football-data.org -> football-data.co.uk).
ALIASES = {
    "manchester united": "Man United", "manchester utd": "Man United", "man utd": "Man United",
    "manchester city": "Man City", "wolverhampton wanderers": "Wolves", "wolverhampton": "Wolves",
    "tottenham hotspur": "Tottenham", "spurs": "Tottenham", "newcastle united": "Newcastle",
    "west ham united": "West Ham", "brighton and hove albion": "Brighton",
    "brighton & hove albion": "Brighton", "nottingham forest": "Nott'm Forest",
    "leicester city": "Leicester", "leeds united": "Leeds", "sheffield united": "Sheffield United",
    "ipswich town": "Ipswich", "luton town": "Luton", "afc bournemouth": "Bournemouth",
    "bayern munchen": "Bayern Munich", "fc bayern munchen": "Bayern Munich",
    "borussia dortmund": "Dortmund", "borussia monchengladbach": "M'gladbach",
    "bayer leverkusen": "Leverkusen", "bayer 04 leverkusen": "Leverkusen",
    "eintracht frankfurt": "Ein Frankfurt", "1. fc koln": "FC Koln", "fc koln": "FC Koln",
    "vfb stuttgart": "Stuttgart", "vfl wolfsburg": "Wolfsburg", "rb leipzig": "RB Leipzig",
    "tsg hoffenheim": "Hoffenheim", "1899 hoffenheim": "Hoffenheim", "sc freiburg": "Freiburg",
    "fc union berlin": "Union Berlin", "1. fc union berlin": "Union Berlin",
    "1. fsv mainz 05": "Mainz", "fsv mainz 05": "Mainz", "werder bremen": "Werder Bremen",
    "fc st. pauli": "St Pauli", "st. pauli": "St Pauli", "1. fc heidenheim": "Heidenheim",
    "fc augsburg": "Augsburg", "vfl bochum": "Bochum", "hamburger sv": "Hamburg",
    "atletico madrid": "Ath Madrid", "atletico de madrid": "Ath Madrid",
    "athletic bilbao": "Ath Bilbao", "athletic club": "Ath Bilbao", "real betis": "Betis",
    "real sociedad": "Sociedad", "celta vigo": "Celta", "rayo vallecano": "Vallecano",
    "espanyol": "Espanol", "rcd espanyol": "Espanol", "deportivo alaves": "Alaves",
    "real valladolid": "Valladolid", "cd leganes": "Leganes", "ud las palmas": "Las Palmas",
    "inter milan": "Inter", "internazionale": "Inter", "ac milan": "Milan", "as roma": "Roma",
    "hellas verona": "Verona", "paris saint germain": "Paris SG", "paris saint-germain": "Paris SG",
    "olympique marseille": "Marseille", "olympique de marseille": "Marseille",
    "olympique lyonnais": "Lyon", "as monaco": "Monaco", "stade rennais": "Rennes",
    "saint etienne": "St Etienne", "as saint-etienne": "St Etienne",
    "legia warszawa": "Legia", "legia warsaw": "Legia", "lech poznan": "Lech Poznan",
    "rakow czestochowa": "Rakow", "jagiellonia bialystok": "Jagiellonia",
}

STOP = {"fc", "cf", "afc", "sc", "ac", "as", "ssc", "us", "rc", "cd", "ud", "sd", "club", "de",
        "calcio", "1.", "ks", "the"}


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    return " ".join(t for t in s.split() if t not in STOP)


@dataclass
class Match:
    raw: str
    canonical: str | None
    score: float
    status: str  # manual | alias | auto | pending


def resolve(raw: str, candidates: list[str], manual: dict[str, str] | None = None) -> Match:
    """raw: nazwa ze zrodla; candidates: nazwy kanoniczne druzyn ligi; manual: decyzje czlowieka."""
    if manual and raw in manual:
        return Match(raw, manual[raw], 1.0, "manual")
    if raw in candidates:
        return Match(raw, raw, 1.0, "auto")
    key = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode().lower().strip()
    if key in ALIASES and ALIASES[key] in candidates:
        return Match(raw, ALIASES[key], 1.0, "alias")
    n = normalize(raw)
    scored = sorted(((difflib.SequenceMatcher(None, n, normalize(c)).ratio(), c) for c in candidates),
                    reverse=True)
    if not scored or scored[0][0] < REVIEW:
        return Match(raw, None, scored[0][0] if scored else 0.0, "pending")
    best, second = scored[0], (scored[1] if len(scored) > 1 else (0.0, None))
    # pewne i jednoznaczne (wyraznie lepsze od drugiego kandydata)
    if best[0] >= AUTO and best[0] - second[0] >= 0.10:
        return Match(raw, best[1], best[0], "auto")
    return Match(raw, best[1], best[0], "pending")


def resolve_many(raws: list[str], candidates: list[str], manual: dict[str, str] | None = None
                 ) -> tuple[dict[str, str], list[Match]]:
    """Zwraca (mapowanie dla pewnych, lista do weryfikacji). Dwie surowe nazwy na jedna kanoniczna
    tez ida do weryfikacji, bo to prawie zawsze blad."""
    out, pending, used = {}, [], {}
    for r in sorted(set(raws)):
        m = resolve(r, candidates, manual)
        if m.status == "pending":
            pending.append(m)
            continue
        if m.canonical in used and m.status == "auto":
            pending.append(Match(r, m.canonical, m.score, "pending"))
            continue
        used[m.canonical] = r
        out[r] = m.canonical
    return out, pending
