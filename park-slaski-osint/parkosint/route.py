"""Trasa spaceru: GPX/TCX/GeoJSON z aplikacji albo punkty wpisane ręcznie.

Z trasą raport liczy dwie odległości dla każdego zdjęcia z geotagiem:
* od linii trasy (czy zdjęcie zrobiono przy Twojej drodze),
* od miejsca, w którym byłeś w chwili zrobienia zdjęcia (gdy trasa ma czasy).
"""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .geo import BBox, haversine_m
from .timeutil import parse_iso_utc

M_PER_DEG_LAT = 111_320.0


@dataclass
class RoutePoint:
    lat: float
    lon: float
    time: datetime | None = None


@dataclass
class Route:
    points: list[RoutePoint]
    source: str = ""
    approx_times: bool = False

    @property
    def timed(self) -> bool:
        return len(self.points) >= 2 and all(p.time for p in self.points)

    @property
    def start(self) -> datetime | None:
        return self.points[0].time if self.timed else None

    @property
    def end(self) -> datetime | None:
        return self.points[-1].time if self.timed else None

    def length_m(self) -> float:
        return sum(haversine_m(a.lat, a.lon, b.lat, b.lon) for a, b in zip(self.points, self.points[1:]))

    def bbox(self, buffer_m: float) -> BBox:
        lats = [p.lat for p in self.points]
        lons = [p.lon for p in self.points]
        dlat = buffer_m / M_PER_DEG_LAT
        dlon = buffer_m / (M_PER_DEG_LAT * math.cos(math.radians(sum(lats) / len(lats))))
        return BBox(min(lats) - dlat, min(lons) - dlon, max(lats) + dlat, max(lons) + dlon)

    def distance_m(self, lat: float, lon: float) -> float:
        """Najmniejsza odległość punktu od łamanej (rzut lokalny, wystarczający na kilka km)."""
        kx = M_PER_DEG_LAT * math.cos(math.radians(lat))

        def xy(p):
            return ((p.lon - lon) * kx, (p.lat - lat) * M_PER_DEG_LAT)

        if len(self.points) == 1:
            return haversine_m(lat, lon, self.points[0].lat, self.points[0].lon)
        best = float("inf")
        for a, b in zip(self.points, self.points[1:]):
            (ax, ay), (bx, by) = xy(a), xy(b)
            dx, dy = bx - ax, by - ay
            seg = dx * dx + dy * dy
            t = 0.0 if seg == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg))
            best = min(best, math.hypot(ax + t * dx, ay + t * dy))
        return best

    def position_at(self, when: datetime) -> tuple[float, float] | None:
        """Gdzie byłeś o danej godzinie (interpolacja liniowa). None poza czasem trasy."""
        if not self.timed or when < self.points[0].time or when > self.points[-1].time:
            return None
        for a, b in zip(self.points, self.points[1:]):
            if a.time <= when <= b.time:
                span = (b.time - a.time).total_seconds()
                f = 0.0 if span == 0 else (when - a.time).total_seconds() / span
                return a.lat + f * (b.lat - a.lat), a.lon + f * (b.lon - a.lon)
        return None

    def timetable(self, step_min: int = 5) -> list[tuple[datetime, float, float]]:
        """Pozycja co step_min minut, od startu do mety (pierwszy i ostatni punkt zawsze)."""
        if not self.timed:
            return []
        out, t = [], self.start
        while t < self.end:
            lat, lon = self.position_at(t)
            out.append((t, lat, lon))
            t = t + timedelta(minutes=step_min) - timedelta(minutes=t.minute % step_min, seconds=t.second)
        out.append((self.end, self.points[-1].lat, self.points[-1].lon))
        return out

    def with_times(self, start: datetime, end: datetime) -> "Route":
        """Dla punktów wpisanych ręcznie: rozkłada czas proporcjonalnie do przebytej drogi
        (zakłada stałe tempo, więc pozycja w danej minucie jest przybliżona)."""
        total = self.length_m() or 1.0
        done, out = 0.0, [RoutePoint(self.points[0].lat, self.points[0].lon, start)]
        for a, b in zip(self.points, self.points[1:]):
            done += haversine_m(a.lat, a.lon, b.lat, b.lon)
            out.append(RoutePoint(b.lat, b.lon, start + (end - start) * (done / total)))
        return Route(out, self.source, approx_times=True)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(el, name: str) -> str | None:
    for c in el.iter():
        if _local(c.tag) == name:
            return c.text
    return None


def parse_points(text: str) -> Route:
    """'50.2795,18.9902; 50.2770,18.9925; ...'"""
    pts = []
    for chunk in text.replace("\n", ";").split(";"):
        if chunk.strip():
            lat, lon = (float(x) for x in chunk.split(","))
            pts.append(RoutePoint(lat, lon))
    if not pts:
        raise ValueError("Pusta lista punktów trasy")
    return Route(pts, "punkty wpisane ręcznie")


def load(path: Path) -> Route:
    text = path.read_text(encoding="utf-8-sig")
    suffix = path.suffix.lower()
    if suffix in (".json", ".geojson"):
        return _from_geojson(json.loads(text), path.name)
    if suffix == ".txt":
        return parse_points(text)
    root = ET.fromstring(text)
    pts = []
    for el in root.iter():
        name = _local(el.tag)
        if name in ("trkpt", "rtept") and el.get("lat"):
            pts.append(RoutePoint(float(el.get("lat")), float(el.get("lon")), parse_iso_utc(_child_text(el, "time"))))
        elif name == "Trackpoint":
            lat, lon = _child_text(el, "LatitudeDegrees"), _child_text(el, "LongitudeDegrees")
            if lat and lon:
                pts.append(RoutePoint(float(lat), float(lon), parse_iso_utc(_child_text(el, "Time"))))
    if not pts:
        raise ValueError(f"{path.name}: nie znalazłem punktów trasy (obsługiwane: GPX, TCX, GeoJSON, txt)")
    return Route(pts, path.name)


def _from_geojson(data: dict, name: str) -> Route:
    geoms = []
    if data.get("type") == "FeatureCollection":
        geoms = [f.get("geometry") or {} for f in data.get("features", [])]
    elif data.get("type") == "Feature":
        geoms = [data.get("geometry") or {}]
    else:
        geoms = [data]
    pts = []
    for g in geoms:
        lines = [g["coordinates"]] if g.get("type") == "LineString" else g.get("coordinates", []) if g.get("type") == "MultiLineString" else []
        for line in lines:
            pts += [RoutePoint(float(c[1]), float(c[0])) for c in line]
    if not pts:
        raise ValueError(f"{name}: brak LineString w GeoJSON")
    return Route(pts, name)
