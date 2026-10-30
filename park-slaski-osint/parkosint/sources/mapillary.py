"""Mapillary API v4: endpoint /images z filtrem bbox i captured_at.

Dokumentacja: https://www.mapillary.com/developer/api-documentation
captured_at to czas z urządzenia (z EXIF/GPS), w milisekundach od epoki UTC.
Duże bbox API odrzuca albo obcina, więc pytamy kafelkami.
"""
from __future__ import annotations

from ..geo import BBox
from ..http import Http, HttpError
from ..models import Item, SourceResult
from ..timeutil import Window, from_epoch_ms, utc_iso

API = "https://graph.mapillary.com/images"
FIELDS = "id,captured_at,computed_geometry,geometry,thumb_256_url,thumb_1024_url,creator,is_pano,sequence,make,model"
LIMIT = 2000


def parse_image(d: dict) -> Item:
    geom = d.get("computed_geometry") or d.get("geometry") or {}
    coords = geom.get("coordinates") or [None, None]
    creator = d.get("creator") or {}
    item = Item(
        source="mapillary",
        source_id=str(d["id"]),
        url=f"https://www.mapillary.com/app/?pKey={d['id']}&focus=photo",
        title=f"Mapillary {'panorama' if d.get('is_pano') else 'zdjęcie'} {d['id']}",
        author=creator.get("username", ""),
        media_type="panorama" if d.get("is_pano") else "photo",
        thumb_url=d.get("thumb_256_url") or d.get("thumb_1024_url"),
        license="CC BY-SA 4.0",
    )
    if d.get("captured_at") is not None:
        item.taken_at = from_epoch_ms(int(d["captured_at"]))
        item.time_kind = "device"
    if coords[0] is not None:
        item.lon, item.lat = float(coords[0]), float(coords[1])
    if d.get("sequence"):
        item.notes.append(f"sekwencja {d['sequence']}")
    model = " ".join(x for x in (d.get("make"), d.get("model")) if x)
    if model:
        item.notes.append(f"aparat: {model}")
    return item


def search(http: Http, token: str, window: Window, bbox: BBox, tile: float = 0.01) -> SourceResult:
    res = SourceResult("mapillary")
    if not token:
        res.skipped = "brak MAPILLARY_ACCESS_TOKEN w .env"
        return res
    headers = {"Authorization": f"OAuth {token}"}
    found: dict[str, Item] = {}
    tiles = bbox.tiles(tile)
    for t in tiles:
        params = {
            "bbox": t.lon_lat_str(),
            "start_captured_at": utc_iso(window.query_start),
            "end_captured_at": utc_iso(window.query_end),
            "fields": FIELDS,
            "limit": LIMIT,
        }
        try:
            data = http.get_json(API, params=params, headers=headers)
        except HttpError as e:
            msg = ((e.payload or {}).get("error") or {}).get("message") if isinstance(e.payload, dict) else None
            res.errors.append(f"kafelek {t.lon_lat_str()}: {msg or e}")
            if e.blocked or e.status in (401, 403):
                break
            continue
        rows = data.get("data", [])
        if len(rows) >= LIMIT:
            res.notes.append(f"kafelek {t.lon_lat_str()} zwrócił limit {LIMIT}, zmniejsz --mapillary-tile")
        for d in rows:
            item = parse_image(d)
            found.setdefault(item.source_id, item)
    res.notes.append(f"{len(tiles)} kafelków, {len(found)} obrazów")
    res.items = list(found.values())
    return res
