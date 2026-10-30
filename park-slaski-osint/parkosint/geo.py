from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class BBox:
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    @classmethod
    def parse(cls, text: str) -> "BBox":
        """'min_lat,min_lon,max_lat,max_lon'"""
        a, b, c, d = (float(x) for x in text.split(","))
        return cls(min(a, c), min(b, d), max(a, c), max(b, d))

    def lon_lat_str(self) -> str:
        """Kolejność Flickr i Mapillary: min_lon,min_lat,max_lon,max_lat."""
        return f"{self.min_lon:.6f},{self.min_lat:.6f},{self.max_lon:.6f},{self.max_lat:.6f}"

    def mediawiki_str(self) -> str:
        """Kolejność geosearch: top|left|bottom|right."""
        return f"{self.max_lat:.6f}|{self.min_lon:.6f}|{self.min_lat:.6f}|{self.max_lon:.6f}"

    @property
    def center(self) -> tuple[float, float]:
        return ((self.min_lat + self.max_lat) / 2, (self.min_lon + self.max_lon) / 2)

    def contains(self, lat: float, lon: float) -> bool:
        return self.min_lat <= lat <= self.max_lat and self.min_lon <= lon <= self.max_lon

    def tiles(self, step: float) -> list["BBox"]:
        out = []
        lat = self.min_lat
        while lat < self.max_lat - 1e-9:
            lon = self.min_lon
            nlat = min(lat + step, self.max_lat)
            while lon < self.max_lon - 1e-9:
                nlon = min(lon + step, self.max_lon)
                out.append(BBox(lat, lon, nlat, nlon))
                lon = nlon
            lat = nlat
        return out


def parse_point(text: str) -> tuple[float, float]:
    lat, lon = (float(x.strip()) for x in text.split(","))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"Niepoprawny punkt: {text}")
    return lat, lon


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def fmt_distance(m: float | None) -> str:
    if m is None:
        return "brak geolokalizacji"
    if m < 1000:
        return f"{round(m / 10) * 10:.0f} m"
    return f"{m / 1000:.2f} km".replace(".", ",")
