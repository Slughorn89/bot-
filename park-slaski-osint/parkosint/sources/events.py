"""Wydarzenia w parku w dniu zdarzenia.

Dwa składniki:
* resources/events_<data>.yaml: ustalenia z researchu, z poziomem pewności i źródłami,
* opcjonalne pobranie publicznych stron obiektów (z robots.txt i limitem zapytań)
  i wyszukanie na nich wzmianek o dacie. Bez logowania i bez wykonywania JS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from ..http import Http, HttpError, RobotsDisallowed
from ..textutil import date_patterns, fold, strip_html

RESOURCES = Path(__file__).resolve().parent.parent / "resources"

VENUE_PAGES = [
    ("Park Śląski", "https://parkslaski.pl/"),
    ("Stadion Śląski", "https://www.stadionslaski.pl/"),
    ("Legendia", "https://legendia.pl/"),
    ("Śląski Ogród Zoologiczny", "https://zoo.silesia.pl/"),
    ("Planetarium Śląskie", "https://www.planetarium.edu.pl/"),
    ("Muzeum GPE (skansen)", "https://muzeumgpe-chorzow.pl/"),
    ("Ruch Chorzów, terminarz", "https://www.ksruch.com/terminarz"),
    ("Tuba Chorzowa, wydarzenia", "https://www.tubachorzowa.pl/wydarzenia"),
    ("Tuba Chorzowa, weekend 16 do 18.10", "https://www.tubachorzowa.pl/artykul/20486,dzieje-sie-w-chorzowie-co-robic-w-weekend-16-18-pazdziernika"),
    ("eBilet, Park Śląski", "https://www.ebilet.pl/miejsce/park-slaski"),
    ("eBilet, Stadion Śląski", "https://www.ebilet.pl/miejsce/stadion-slaski"),
    ("Biletyna, Park Śląski", "https://biletyna.pl/Chorzow/Park-Slaski"),
]


@dataclass
class PageHit:
    venue: str
    url: str
    status: str
    snippets: list[str] = field(default_factory=list)


@dataclass
class EventsResult:
    known: list[dict] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    pages: list[PageHit] = field(default_factory=list)


def load_known(day: date) -> tuple[list[dict], dict[str, str]]:
    path = RESOURCES / f"events_{day.isoformat()}.yaml"
    if not path.exists():
        return [], {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("events", []), data.get("sources", {})


def find_snippets(text: str, day: date, width: int = 160, limit: int = 6) -> list[str]:
    # wycinek bierzemy z tekstu po fold() (bez polskich znaków), żeby pozycje dopasowań się zgadzały
    folded = fold(strip_html(text))
    out = []
    for rx in date_patterns(day):
        for m in rx.finditer(folded):
            s = max(0, m.start() - width)
            snippet = folded[s:m.end() + width].strip()
            if snippet not in out:
                out.append(snippet)
            if len(out) >= limit:
                return out
    return out


def check_pages(http: Http, day: date, pages=VENUE_PAGES) -> list[PageHit]:
    hits = []
    for venue, url in pages:
        try:
            text = http.get_text(url, robots=True)
        except RobotsDisallowed as e:
            hits.append(PageHit(venue, url, f"{e}. Sprawdź ręcznie."))
            continue
        except HttpError as e:
            hits.append(PageHit(venue, url, f"niedostępne: {e}"))
            continue
        snippets = find_snippets(text, day)
        hits.append(PageHit(venue, url, f"{len(snippets)} wzmianek o dacie" if snippets else "brak wzmianki o dacie na tej stronie", snippets))
    return hits


def collect(http: Http | None, day: date, fetch_pages: bool = True) -> EventsResult:
    known, sources = load_known(day)
    res = EventsResult(known=known, sources=sources)
    if fetch_pages and http is not None:
        res.pages = check_pages(http, day)
    else:
        res.pages = [PageHit(v, u, "nie pobierano, sprawdź ręcznie") for v, u in VENUE_PAGES]
    return res
