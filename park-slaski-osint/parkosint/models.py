from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from .geo import haversine_m
from .timeutil import Window

TIME_KINDS = {
    "exif": "EXIF DateTimeOriginal",
    "taken": "czas wykonania wg serwisu",
    "device": "czas z urządzenia",
    "live": "start transmisji na żywo",
    "recording_date": "data nagrania od autora (bez godziny)",
    "date_only": "tylko data wykonania",
    "published": "czas publikacji, NIE wykonania",
    "unknown": "brak",
}
# rodzaje czasu na tyle dokładne, żeby porównywać je z godziną na trasie
PRECISE_TIME = {"exif", "taken", "device", "live"}


@dataclass
class Item:
    source: str
    source_id: str
    url: str
    title: str = ""
    author: str = ""
    media_type: str = "photo"
    thumb_url: str | None = None
    taken_at: datetime | None = None
    taken_end: datetime | None = None
    time_kind: str = "unknown"
    published_at: datetime | None = None
    lat: float | None = None
    lon: float | None = None
    description: str = ""
    license: str = ""
    notes: list[str] = field(default_factory=list)
    score: int | None = None
    window_status: str | None = None
    distance_m: float | None = None
    dist_route_m: float | None = None
    dist_you_m: float | None = None
    local_thumb: str | None = None

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def sort_time(self) -> datetime | None:
        return self.taken_at or self.published_at

    def finalize(self, window: Window, point: tuple[float, float] | None, route=None) -> None:
        if self.taken_at and self.taken_end:
            self.window_status = window.classify_range(self.taken_at, self.taken_end)
        else:
            self.window_status = window.classify(self.taken_at)
        if self.lat is None or self.lon is None:
            return
        if point:
            self.distance_m = haversine_m(point[0], point[1], self.lat, self.lon)
        if route is not None:
            self.dist_route_m = route.distance_m(self.lat, self.lon)
            if self.taken_at and self.time_kind in PRECISE_TIME:
                pos = route.position_at(self.taken_at)
                if pos:
                    self.dist_you_m = haversine_m(pos[0], pos[1], self.lat, self.lon)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("taken_at", "taken_end", "published_at"):
            d[k] = d[k].isoformat() if d[k] else None
        d["time_kind_label"] = TIME_KINDS.get(self.time_kind, self.time_kind)
        return d


@dataclass
class SourceResult:
    name: str
    items: list[Item] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: str | None = None

    @property
    def status(self) -> str:
        if self.skipped:
            return "pominięte"
        if self.errors and not self.items:
            return "błąd"
        if self.errors:
            return "częściowo"
        return "ok"
