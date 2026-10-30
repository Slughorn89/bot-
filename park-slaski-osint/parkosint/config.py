"""Ustawienia domyślne. Wszystko da się nadpisać z .env albo z linii poleceń."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path

from dotenv import load_dotenv

from .geo import BBox, parse_point

ROOT = Path(__file__).resolve().parent.parent

# Prostokąt Parku Śląskiego z zapasem (ok. 4,3 x 3,9 km), dobrany do obiektów z LANDMARKS
# i do północnego skraju parku przy ul. Siemianowickiej. Łapie też fragmenty Chorzowa i Katowic
# przy granicach, odległość od trasy w raporcie pozwala to odsiać. Zmienisz go przez PARK_BBOX w .env.
DEFAULT_BBOX = "50.2660,18.9600,50.3050,19.0150"

# Współrzędne obiektów z Wikipedii / Wikidata (sprawdzone 30.10.2026)
LANDMARKS = {
    "Stadion Śląski": (50.288333, 18.973611),
    "Planetarium Śląskie": (50.290653, 18.992303),
    "Kąpielisko Fala": (50.285965, 18.985703),
    "Śląski Ogród Zoologiczny": (50.281661, 18.993473),
    "Legendia": (50.273763, 18.990555),
}

DEFAULT_DATE = date(2026, 10, 17)
DEFAULT_START = time(16, 5)
DEFAULT_END = time(17, 30)

# Punkt odniesienia do liczenia odległości: --point albo REFERENCE_POINT w .env. Bez nich, gdy podano
# trasę, liczymy od jej startu. Współrzędnych z okolic domu nie wpisujemy tutaj, bo repo jest publiczne.
DEFAULT_POINT = None

# Obiekty w parku: nazwy do linków Google Maps i fraz wyszukiwania.
POIS = [
    "Park Śląski Chorzów",
    "Stadion Śląski Chorzów",
    "Legendia Śląskie Wesołe Miasteczko",
    "Śląski Ogród Zoologiczny Chorzów",
    "Planetarium Śląskie Chorzów",
    "Muzeum Górnośląski Park Etnograficzny w Chorzowie",
    "Kolej linowa Elka Park Śląski",
    "Rosarium Park Śląski",
    "Hala Kapelusz Park Śląski",
]

YOUTUBE_PHRASES = [
    "Park Śląski",
    "Chorzów",
    "Stadion Śląski",
    "Legendia",
    "Śląskie Zoo Chorzów",
    "Planetarium Śląskie",
    "Skansen Chorzów",
    "Park Śląski 17.10.2026",
]

FLICKR_TEXT_QUERIES = ["Chorzów", "Park Śląski", "Stadion Śląski", "Legendia", "Silesian Park"]

COMMONS_CATEGORIES = [
    "Park Śląski",
    "Silesian Park",
    "Silesian Culture and Recreation Park",
    "Stadion Śląski",
    "Legendia",
    "Silesian Zoological Garden",
    "Silesian Planetarium",
    "Upper Silesian Ethnographic Park",
]

INSTAGRAM_TAGS = [
    "parkslaski", "parkslaskichorzow", "chorzow", "stadionslaski",
    "legendia", "slaskiezoo", "planetariumslaskie", "skansenchorzow",
]


@dataclass
class Settings:
    flickr_key: str = ""
    mapillary_token: str = ""
    youtube_key: str = ""
    windy_key: str = ""
    contact: str = ""
    point: tuple[float, float] | None = DEFAULT_POINT
    bbox: BBox = field(default_factory=lambda: BBox.parse(DEFAULT_BBOX))
    instagram_location_ids: list[str] = field(default_factory=list)
    route_file: str = ""
    route_start: str = ""
    route_end: str = ""

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        load_dotenv(env_file or ROOT / ".env")
        point = os.getenv("REFERENCE_POINT", "").strip()
        ig = os.getenv("INSTAGRAM_LOCATION_IDS", "").strip()
        return cls(
            flickr_key=os.getenv("FLICKR_API_KEY", "").strip(),
            mapillary_token=os.getenv("MAPILLARY_ACCESS_TOKEN", "").strip(),
            youtube_key=os.getenv("YOUTUBE_API_KEY", "").strip(),
            windy_key=os.getenv("WINDY_WEBCAMS_API_KEY", "").strip(),
            contact=os.getenv("CONTACT_EMAIL", "").strip(),
            point=parse_point(point) if point else DEFAULT_POINT,
            bbox=BBox.parse(os.getenv("PARK_BBOX", DEFAULT_BBOX)),
            instagram_location_ids=[x.strip() for x in ig.split(",") if x.strip()],
            route_file=os.getenv("ROUTE_FILE", "").strip(),
            route_start=os.getenv("ROUTE_START", "").strip(),
            route_end=os.getenv("ROUTE_END", "").strip(),
        )
