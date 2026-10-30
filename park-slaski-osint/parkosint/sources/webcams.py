"""Publiczne kamery internetowe w pobliżu parku przez Windy Webcams API v3.

Dokumentacja: https://api.windy.com/webcams/docs
Pole 'player' zawiera linki do timelapse'ów: day (24 h), month (30 dni), year, lifetime.
W darmowym planie część z nich bywa niedostępna, więc pokazujemy to, co API zwróci.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..geo import haversine_m
from ..http import Http, HttpError

API = "https://api.windy.com/webcams/api/v3/webcams"
ARCHIVE_SPANS = {"day": 1, "month": 30, "year": 365, "lifetime": 100000}


@dataclass
class Webcam:
    id: str
    title: str
    lat: float | None
    lon: float | None
    status: str
    detail_url: str
    preview: str | None
    players: dict[str, str] = field(default_factory=dict)
    distance_center_m: float | None = None
    distance_point_m: float | None = None

    def archive_note(self, target: date, today: date) -> str:
        age = (today - target).days
        covering = [k for k, span in ARCHIVE_SPANS.items() if k in self.players and span >= age]
        if not self.players:
            return "API nie zwróciło żadnego timelapse'u (może wymagać płatnego planu)"
        if covering:
            return f"timelapse {', '.join(covering)} może obejmować {target:%d.%m} (klatki co kilka minut, bez szczegółów)"
        return f"dostępne timelapse'y ({', '.join(self.players)}) nie sięgają {target:%d.%m}"


@dataclass
class WebcamResult:
    cams: list[Webcam] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: str | None = None


def parse_cam(d: dict, center, point) -> Webcam:
    loc = d.get("location") or {}
    images = (d.get("images") or {}).get("current") or {}
    players = {k: v for k, v in (d.get("player") or {}).items() if isinstance(v, str) and v}
    cam = Webcam(
        id=str(d.get("webcamId") or d.get("id")),
        title=d.get("title", ""),
        lat=loc.get("latitude"),
        lon=loc.get("longitude"),
        status=d.get("status", ""),
        detail_url=(d.get("urls") or {}).get("detail", ""),
        preview=images.get("preview") or images.get("thumbnail"),
        players=players,
    )
    if cam.lat is not None and cam.lon is not None:
        cam.distance_center_m = haversine_m(center[0], center[1], cam.lat, cam.lon)
        if point:
            cam.distance_point_m = haversine_m(point[0], point[1], cam.lat, cam.lon)
    return cam


def search(http: Http, key: str, center: tuple[float, float], point, radius_km: int = 6) -> WebcamResult:
    res = WebcamResult()
    if not key:
        res.skipped = "brak WINDY_WEBCAMS_API_KEY w .env (kamery sprawdzisz ręcznie z linków)"
        return res
    try:
        data = http.get_json(API, params={
            "nearby": f"{center[0]:.5f},{center[1]:.5f},{radius_km}",
            "include": "location,images,player,urls",
            "limit": 50,
            "lang": "pl",
        }, headers={"x-windy-api-key": key})
    except HttpError as e:
        res.errors.append(str(e))
        return res
    res.cams = sorted((parse_cam(d, center, point) for d in data.get("webcams", [])),
                      key=lambda c: c.distance_center_m if c.distance_center_m is not None else 1e12)
    return res
