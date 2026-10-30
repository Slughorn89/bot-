"""YouTube Data API v3: search.list po frazach + videos.list po szczegóły.

Koszt: search.list = 100 jednostek, videos.list = 1 jednostka (dzienny limit 10 000).
YouTube nie podaje czasu nagrania, więc wynik filtrujemy po tytule i opisie,
a czas bierzemy kolejno: start transmisji live, recordingDate od autora, publikacja.
"""
from __future__ import annotations

import re

from ..http import Http, HttpError
from ..models import Item, SourceResult
from ..textutil import date_patterns, fold
from ..timeutil import Window, parse_iso_utc, parse_date_only, utc_iso

SEARCH = "https://www.googleapis.com/youtube/v3/search"
VIDEOS = "https://www.googleapis.com/youtube/v3/videos"

# (wzorzec na tekście po fold(), waga)
PLACE_PATTERNS = [
    (r"\bpark\w* slask\w*", 3),
    (r"\bstadion\w* slask\w*", 3),
    (r"\blegendi\w*", 3),
    (r"\bslask\w* wesol\w* miasteczk\w*", 3),
    (r"\bslask\w* ogrod\w* zoolog\w*", 3),
    (r"\bplanetari\w* slask\w*", 3),
    (r"\bgornoslask\w* park\w* etnograf\w*", 3),
    (r"\bsilesian (park|stadium|zoo|planetarium)\b", 3),
    (r"\bkolej\w* (linow\w* )?elka\b", 3),
    (r"\bhal\w* kapelusz\b", 3),
    (r"\bchorzow\w*", 2),
    (r"\bslaski\w* zoo\b|\bzoo\b.{0,25}\bchorzow", 2),
    (r"\bskansen\w*", 1),
    (r"\brosarium\b", 1),
]
_PLACE_RE = [(re.compile(p), w) for p, w in PLACE_PATTERNS]


def score_text(title: str, description: str, day) -> tuple[int, int, list[str]]:
    """Zwraca (punkty za miejsce, punkty za datę, trafione frazy)."""
    text = fold(f"{title} \n {description}")
    place, hits = 0, []
    for rx, w in _PLACE_RE:
        m = rx.search(text)
        if m:
            place += w
            hits.append(m.group(0))
    date_score = 0
    for rx in date_patterns(day):
        m = rx.search(text)
        if m:
            date_score = 3
            hits.append(m.group(0))
            break
    if not date_score and re.search(r"\bsobot\w*|\bsaturday\b", text):
        date_score = 1
    return place, date_score, hits


def search(http: Http, key: str, window: Window, phrases: list[str], pages: int = 2,
           min_score: int = 2) -> SourceResult:
    res = SourceResult("youtube")
    if not key:
        res.skipped = "brak YOUTUBE_API_KEY w .env"
        return res
    ids: dict[str, str] = {}
    quota = 0
    stop = False
    for phrase in phrases:
        if stop:
            break
        token = None
        for _ in range(pages):
            params = {
                "part": "snippet", "q": phrase, "type": "video", "order": "date",
                "publishedAfter": utc_iso(window.start), "maxResults": 50,
                "regionCode": "PL", "relevanceLanguage": "pl", "key": key,
            }
            if token:
                params["pageToken"] = token
            try:
                data = http.get_json(SEARCH, params=params)
            except HttpError as e:
                res.errors.append(f"search '{phrase}': {_reason(e)}")
                # zły klucz albo wyczerpana kwota: kolejne frazy też nie przejdą
                stop = e.blocked or e.status in (400, 401, 403)
                break
            quota += 100
            for it in data.get("items", []):
                vid = (it.get("id") or {}).get("videoId")
                if vid:
                    ids.setdefault(vid, phrase)
            token = data.get("nextPageToken")
            if not token:
                break
    return _details(http, key, window, ids, res, quota, min_score)


def _reason(e: HttpError) -> str:
    if isinstance(e.payload, dict):
        err = e.payload.get("error") or {}
        reasons = ",".join(x.get("reason", "") for x in err.get("errors", []))
        return f"{err.get('code')} {reasons} {err.get('message', '')}".strip()
    return str(e)


def _details(http, key, window, ids, res, quota, min_score) -> SourceResult:
    vids = list(ids)
    for i in range(0, len(vids), 50):
        chunk = vids[i:i + 50]
        try:
            data = http.get_json(VIDEOS, params={
                "part": "snippet,recordingDetails,liveStreamingDetails,contentDetails",
                "id": ",".join(chunk), "key": key, "maxResults": 50,
            })
        except HttpError as e:
            res.errors.append(f"videos.list: {_reason(e)}")
            continue
        quota += 1
        for v in data.get("items", []):
            item = parse_video(v, window)
            if item is None or (item.score or 0) < min_score:
                continue
            item.notes.append(f"fraza: {ids.get(item.source_id)}")
            res.items.append(item)
    res.notes.append(f"{len(vids)} filmów z wyszukiwania, {len(res.items)} po filtrze treści, zużyto ok. {quota} jednostek kwoty")
    return res


def parse_video(v: dict, window: Window) -> Item | None:
    sn = v.get("snippet") or {}
    title, desc = sn.get("title", ""), sn.get("description", "")
    place, date_score, hits = score_text(title, desc, window.day)
    item = Item(
        source="youtube",
        source_id=v["id"],
        url=f"https://www.youtube.com/watch?v={v['id']}",
        title=title,
        author=sn.get("channelTitle", ""),
        media_type="video",
        thumb_url=((sn.get("thumbnails") or {}).get("medium") or {}).get("url"),
        published_at=parse_iso_utc(sn.get("publishedAt")),
        description=desc[:500],
    )
    score = place + date_score if place else 0
    live_details = v.get("liveStreamingDetails") or {}
    live = parse_iso_utc(live_details.get("actualStartTime"))
    rec = (v.get("recordingDetails") or {})
    rec_date = parse_date_only(rec.get("recordingDate", ""))
    if live:
        item.taken_at, item.time_kind = live, "live"
        item.taken_end = parse_iso_utc(live_details.get("actualEndTime"))
        if window.classify_range(live, item.taken_end) in ("in", "margin"):
            score += 5
    elif rec_date:
        item.time_kind = "recording_date"
        item.notes.append(f"recordingDate: {rec_date:%d.%m.%Y}")
        if rec_date == window.day:
            score += 4
    else:
        item.time_kind = "published"
    loc = rec.get("location") or {}
    if loc.get("latitude") is not None and loc.get("longitude") is not None:
        item.lat, item.lon = float(loc["latitude"]), float(loc["longitude"])
        item.notes.append("lokalizacja nagrania podana przez autora")
    if hits:
        item.notes.append("trafienia: " + ", ".join(dict.fromkeys(hits)))
    item.score = score
    return item
