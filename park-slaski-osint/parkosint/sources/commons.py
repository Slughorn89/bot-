"""Wikimedia Commons: pliki z kategorii parku z datą wykonania w zadanym dniu.

Trzy strategie (wyniki łączone):
1. kategorie parku rekurencyjnie, pliki dodane do kategorii od dnia zdarzenia,
2. CirrusSearch w kategorii "Photographs taken on RRRR-MM-DD" zawężony do Chorzowa i okolicy,
3. opcjonalnie skan geosearch po kafelkach bbox (--commons-geo-scan).
Data wykonania z extmetadata DateTimeOriginal (pochodzi z EXIF albo z opisu pliku).
API: https://www.mediawiki.org/wiki/API:Main_page, zasady: https://www.mediawiki.org/wiki/API:Etiquette
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time

from ..geo import BBox
from ..http import Http, HttpError
from ..models import Item, SourceResult
from ..textutil import strip_html
from ..timeutil import TZ, Window, parse_date_only, parse_iso_utc, parse_local, utc_iso

log = logging.getLogger(__name__)

API = "https://commons.wikimedia.org/w/api.php"
EXT_FILTER = "DateTimeOriginal|DateTime|GPSLatitude|GPSLongitude|LicenseShortName|ObjectName|ImageDescription|Artist"
FILE_PROPS = {
    "prop": "imageinfo|coordinates",
    "iiprop": "url|timestamp|user|extmetadata|mediatype",
    "iiextmetadatafilter": EXT_FILTER,
    "iiurlwidth": 320,
    "coprimary": "all",
}


class Commons:
    def __init__(self, http: Http):
        self.http = http

    def query(self, params: dict, max_rounds: int = 20):
        """Pętla po 'continue'. Zwraca kolejne obiekty 'query'."""
        base = {"action": "query", "format": "json", "formatversion": 2, "maxlag": 5, **params}
        cont: dict = {}
        for _ in range(max_rounds):
            data = self.http.get_json(API, params={**base, **cont})
            if "error" in data:
                code = data["error"].get("code")
                if code == "maxlag":
                    self.http._sleep(5)
                    continue
                raise HttpError(f"Commons API: {code}: {data['error'].get('info')}")
            yield data.get("query") or {}
            if "continue" not in data:
                return
            cont = data["continue"]

    def existing_categories(self, names: list[str]) -> list[str]:
        titles = [f"Category:{n}" for n in names]
        out = []
        for q in self.query({"titles": "|".join(titles), "prop": "categoryinfo"}):
            for page in q.get("pages", []):
                if not page.get("missing"):
                    out.append(page["title"])
        return out

    def discover_categories(self, terms: list[str]) -> list[str]:
        out = []
        for term in terms:
            for q in self.query({"list": "search", "srnamespace": 14, "srsearch": term, "srlimit": 20}, max_rounds=1):
                for hit in q.get("search", []):
                    title = hit["title"]
                    if re.search(r"(?i)park śląski|silesian (culture|park)|chorzów", title):
                        out.append(title)
        return out

    def subcategories(self, roots: list[str], depth: int, cap: int = 80) -> list[str]:
        seen, frontier = list(dict.fromkeys(roots)), list(dict.fromkeys(roots))
        for _ in range(depth):
            nxt = []
            for cat in frontier:
                for q in self.query({"list": "categorymembers", "cmtitle": cat, "cmtype": "subcat", "cmlimit": 500}, max_rounds=3):
                    for m in q.get("categorymembers", []):
                        if m["title"] not in seen and len(seen) < cap:
                            seen.append(m["title"])
                            nxt.append(m["title"])
            frontier = nxt
        return seen

    def files_in_category(self, cat: str, since: datetime) -> list[dict]:
        pages = []
        for q in self.query({
            "generator": "categorymembers", "gcmtitle": cat, "gcmtype": "file",
            "gcmsort": "timestamp", "gcmdir": "newer", "gcmstart": utc_iso(since), "gcmlimit": 50,
            **FILE_PROPS,
        }):
            pages.extend(q.get("pages", []))
        return pages

    def search_files(self, srsearch: str, max_rounds: int = 10) -> list[dict]:
        pages = []
        for q in self.query({
            "generator": "search", "gsrnamespace": 6, "gsrsearch": srsearch, "gsrlimit": 50,
            **FILE_PROPS,
        }, max_rounds=max_rounds):
            pages.extend(q.get("pages", []))
        return pages

    def geo_pageids(self, bbox: BBox) -> list[int]:
        ids = []
        for q in self.query({"list": "geosearch", "gsbbox": bbox.mediawiki_str(), "gsnamespace": 6, "gslimit": 500,
                             "gsprimary": "all"}, max_rounds=1):
            ids.extend(x["pageid"] for x in q.get("geosearch", []))
        return ids

    def files_by_ids(self, pageids: list[int]) -> list[dict]:
        pages = []
        for i in range(0, len(pageids), 50):
            for q in self.query({"pageids": "|".join(map(str, pageids[i:i + 50])), **FILE_PROPS}):
                pages.extend(q.get("pages", []))
        return pages


def _ext(meta: dict, key: str) -> str:
    return strip_html(str((meta.get(key) or {}).get("value", "")))


def parse_taken(raw_html: str) -> tuple[datetime | None, date | None]:
    """DateTimeOriginal z Commons bywa czystym EXIF-em albo HTML-em typu
    '<time datetime="2026-10-17">17 października 2026</time> 17:10'. Zwraca (czas, sama data)."""
    text = strip_html(raw_html)
    dt = parse_local(text)
    if dt:
        return dt, dt.astimezone(TZ).date()
    m = re.search(r'datetime="(\d{4}-\d{2}-\d{2})', raw_html or "")
    day = parse_date_only(m.group(1)) if m else parse_date_only(text)
    if day is None:
        return None, None
    t = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", text)
    if t:
        return datetime(day.year, day.month, day.day, int(t.group(1)), int(t.group(2)), int(t.group(3) or 0), tzinfo=TZ), day
    return None, day


def parse_file(page: dict, window: Window) -> Item | None:
    """Zwraca Item tylko gdy data wykonania wypada w dniu zdarzenia."""
    infos = page.get("imageinfo") or []
    if not infos:
        return None
    ii = infos[0]
    meta = ii.get("extmetadata") or {}
    raw = str((meta.get("DateTimeOriginal") or {}).get("value", ""))
    taken, day = parse_taken(raw)
    if day != window.day:
        return None
    kind = "exif" if taken else "date_only"
    item = Item(
        source="commons",
        source_id=str(page.get("pageid")),
        url=ii.get("descriptionurl") or f"https://commons.wikimedia.org/?curid={page.get('pageid')}",
        title=_ext(meta, "ObjectName") or page.get("title", ""),
        author=_ext(meta, "Artist") or ii.get("user", ""),
        media_type="video" if ii.get("mediatype") == "VIDEO" else "photo",
        thumb_url=ii.get("thumburl"),
        taken_at=taken,
        time_kind=kind,
        published_at=parse_iso_utc(ii.get("timestamp")),
        description=_ext(meta, "ImageDescription")[:500],
        license=_ext(meta, "LicenseShortName"),
    )
    if kind == "date_only":
        item.notes.append(f"DateTimeOriginal: '{strip_html(raw)}' (bez godziny)")
    coords = page.get("coordinates") or []
    if coords:
        item.lat, item.lon = float(coords[0]["lat"]), float(coords[0]["lon"])
    else:
        lat, lon = _ext(meta, "GPSLatitude"), _ext(meta, "GPSLongitude")
        try:
            item.lat, item.lon = float(lat), float(lon)
        except ValueError:
            pass
    return item


def search(http: Http, window: Window, bbox: BBox, categories: list[str], depth: int = 2,
           geo_scan: bool = False) -> SourceResult:
    res = SourceResult("commons")
    api = Commons(http)
    since = datetime.combine(window.day, time(0, 0), tzinfo=TZ)
    pages: dict[int, dict] = {}

    def add(found: list[dict], label: str):
        for p in found:
            if "pageid" in p:
                pages.setdefault(p["pageid"], {**p, "_via": label})

    try:
        cats = api.existing_categories(categories)
        cats += api.discover_categories(["Park Śląski Chorzów", "Silesian Park Chorzów"])
        cats = list(dict.fromkeys(cats))
        res.notes.append("kategorie startowe: " + (", ".join(cats) or "nie znaleziono"))
        all_cats = api.subcategories(cats, depth)
        res.notes.append(f"przeszukano {len(all_cats)} kategorii (głębokość {depth})")
        for cat in all_cats:
            add(api.files_in_category(cat, since), cat)
    except HttpError as e:
        res.errors.append(f"kategorie: {e}")
        if e.blocked:
            return res

    lat, lon = bbox.center
    day = window.day.isoformat()
    queries = [
        f'incategory:"Photographs_taken_on_{day}" Chorzów',
        f'incategory:"Photographs_taken_on_{day}" "Park Śląski"',
        f'incategory:"Photographs_taken_on_{day}" nearcoord:4km,{lat:.4f},{lon:.4f}',
        f'"{day}" Chorzów',
    ]
    for q in queries:
        try:
            add(api.search_files(q), f"szukaj: {q}")
        except HttpError as e:
            res.errors.append(f"szukaj '{q}': {e}")

    if geo_scan:
        try:
            ids: list[int] = []
            for t in bbox.tiles(0.01):
                got = api.geo_pageids(t)
                if len(got) >= 500:
                    res.notes.append(f"geosearch: kafelek {t.lon_lat_str()} ma 500+ plików, część pominięta")
                ids.extend(got)
            ids = [i for i in dict.fromkeys(ids) if i not in pages]
            add(api.files_by_ids(ids), "geosearch")
        except HttpError as e:
            res.errors.append(f"geosearch: {e}")

    for p in pages.values():
        item = parse_file(p, window)
        if item:
            item.notes.append(f"znalezione przez: {p['_via']}")
            res.items.append(item)
    res.notes.append(f"{len(pages)} plików kandydatów, {len(res.items)} z datą wykonania {window.day:%d.%m.%Y}")
    return res
