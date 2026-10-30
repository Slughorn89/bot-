"""Flickr: flickr.photos.search (bbox + zakres taken_date) i flickr.photos.getExif.

Dokumentacja: https://www.flickr.com/services/api/flickr.photos.search.html
Flickr trzyma date_taken jako czas lokalny aparatu bez strefy, więc zapytanie
wysyłamy w czasie Europe/Warsaw (format MySQL datetime).
"""
from __future__ import annotations

import logging

from ..geo import BBox
from ..http import Http, HttpError
from ..models import Item, SourceResult
from ..timeutil import Window, from_epoch_ms, local_naive_str, parse_local

log = logging.getLogger(__name__)

API = "https://api.flickr.com/services/rest/"
EXTRAS = "date_taken,date_upload,geo,owner_name,url_q,url_n,url_m,media,description,tags,license"


class FlickrError(Exception):
    pass


def _call(http: Http, key: str, method: str, **params) -> dict:
    data = http.get_json(API, params={
        "method": method, "api_key": key, "format": "json", "nojsoncallback": 1, **params,
    })
    if data.get("stat") != "ok":
        raise FlickrError(f"{method}: kod {data.get('code')}: {data.get('message')}")
    return data


def parse_photo(p: dict) -> Item:
    owner = p.get("owner", "")
    item = Item(
        source="flickr",
        source_id=str(p["id"]),
        url=f"https://www.flickr.com/photos/{owner}/{p['id']}",
        title=p.get("title") or "",
        author=p.get("ownername") or owner,
        media_type="video" if p.get("media") == "video" else "photo",
        thumb_url=p.get("url_n") or p.get("url_q") or p.get("url_m"),
        description=(p.get("description") or {}).get("_content", "")[:500],
        license=f"Flickr license id {p.get('license')}" if p.get("license") is not None else "",
    )
    if str(p.get("datetakenunknown", "0")) != "1":
        item.taken_at = parse_local(p.get("datetaken", ""))
        item.time_kind = "taken" if item.taken_at else "unknown"
    else:
        item.notes.append("Flickr nie zna daty wykonania")
    if p.get("dateupload"):
        item.published_at = from_epoch_ms(int(p["dateupload"]) * 1000)
    try:
        lat, lon = float(p.get("latitude") or 0), float(p.get("longitude") or 0)
    except ValueError:
        lat = lon = 0.0
    if lat or lon:
        item.lat, item.lon = lat, lon
    return item


def apply_exif(item: Item, exif: list[dict]) -> None:
    tags = {e.get("tag"): (e.get("raw") or {}).get("_content", "") for e in exif}
    original = tags.get("DateTimeOriginal") or tags.get("CreateDate")
    if original:
        dt = parse_local(original, tags.get("OffsetTimeOriginal") or tags.get("OffsetTime"))
        if dt:
            item.taken_at = dt
            item.time_kind = "exif"
    model = " ".join(x for x in (tags.get("Make"), tags.get("Model")) if x)
    if model:
        item.notes.append(f"aparat: {model}")


def search(http: Http, key: str, window: Window, bbox: BBox, text_queries: list[str],
           fetch_exif: bool = True, max_pages: int = 8) -> SourceResult:
    res = SourceResult("flickr")
    if not key:
        res.skipped = "brak FLICKR_API_KEY w .env"
        return res
    base = {
        "min_taken_date": local_naive_str(window.query_start),
        "max_taken_date": local_naive_str(window.query_end),
        "extras": EXTRAS,
        "media": "all",
        "per_page": 250,
        "sort": "date-taken-asc",
        "privacy_filter": 1,
    }
    queries = [("geo bbox", {"bbox": bbox.lon_lat_str()})] + [(f"tekst '{q}'", {"text": q}) for q in text_queries]
    found: dict[str, Item] = {}
    for label, extra in queries:
        page, pages = 1, 1
        while page <= min(pages, max_pages):
            try:
                data = _call(http, key, "flickr.photos.search", page=page, **base, **extra)
            except (HttpError, FlickrError) as e:
                res.errors.append(f"{label}: {e}")
                if getattr(e, "blocked", False):
                    return res
                break
            photos = data.get("photos", {})
            pages = int(photos.get("pages") or 1)
            for p in photos.get("photo", []):
                item = parse_photo(p)
                if item.source_id not in found:
                    item.notes.append(f"zapytanie: {label}")
                    found[item.source_id] = item
            if page == 1:
                res.notes.append(f"{label}: {photos.get('total', 0)} wyników")
            page += 1
        if pages > max_pages:
            res.notes.append(f"{label}: obcięto do {max_pages} stron")

    if fetch_exif:
        for item in found.values():
            try:
                data = _call(http, key, "flickr.photos.getExif", photo_id=item.source_id)
            except FlickrError as e:
                item.notes.append("EXIF niedostępny (autor go ukrył)" if "kod 2" in str(e) else f"EXIF: {e}")
                continue
            except HttpError as e:
                item.notes.append(f"EXIF: {e}")
                continue
            apply_exif(item, data.get("photo", {}).get("exif", []))
    res.items = list(found.values())
    return res
