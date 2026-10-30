from datetime import datetime

from conftest import FakeHttp

from parkosint.geo import BBox
from parkosint.http import HttpError
from parkosint.sources import commons, flickr, mapillary, youtube
from parkosint.sources.events import find_snippets
from parkosint.timeutil import TZ

BBOX = BBox.parse("50.2600,18.9600,50.2960,19.0150")


def test_flickr_search_dedupes_and_reads_exif(window):
    photo_geo = {"id": "111", "owner": "12@N01", "secret": "s", "server": "1", "title": "Rosarium",
                 "datetaken": "2026-10-17 16:40:00", "datetakenunknown": "0", "dateupload": "1760720000",
                 "latitude": "50.2801", "longitude": "18.9912", "ownername": "Ala", "media": "photo",
                 "url_n": "https://live.staticflickr.com/1/111_s_n.jpg", "description": {"_content": "spacer"}}
    photo_nogeo = {"id": "222", "owner": "34@N01", "title": "Chorzów", "datetaken": "2026-10-17 17:05:00",
                   "datetakenunknown": "0", "latitude": 0, "longitude": 0, "media": "video"}

    def handler(url, p, h):
        if p["method"] == "flickr.photos.search":
            photos = [photo_geo] if "bbox" in p else [photo_geo, photo_nogeo]
            return {"photos": {"page": 1, "pages": 1, "total": len(photos), "photo": photos}, "stat": "ok"}
        if p["photo_id"] == "111":
            return {"photo": {"exif": [{"tag": "DateTimeOriginal", "raw": {"_content": "2026:10:17 16:41:30"}},
                                       {"tag": "Model", "raw": {"_content": "Pixel 8"}}]}, "stat": "ok"}
        return {"stat": "fail", "code": 2, "message": "Permission denied"}

    http = FakeHttp(handler)
    res = flickr.search(http, "KEY", window, BBOX, ["Chorzów"])
    assert res.errors == []
    by_id = {i.source_id: i for i in res.items}
    assert set(by_id) == {"111", "222"}
    geo_call = http.calls[0][1]
    assert geo_call["bbox"] == "18.960000,50.260000,19.015000,50.296000"
    assert geo_call["min_taken_date"] == "2026-10-17 15:45:00"
    a = by_id["111"]
    assert a.time_kind == "exif" and a.taken_at == datetime(2026, 10, 17, 16, 41, 30, tzinfo=TZ)
    assert a.lat == 50.2801 and a.url == "https://www.flickr.com/photos/12@N01/111"
    b = by_id["222"]
    assert b.lat is None and b.media_type == "video" and b.time_kind == "taken"
    assert any("ukrył" in n for n in b.notes)


def test_flickr_without_key_is_skipped(window):
    res = flickr.search(FakeHttp(lambda *a: {}), "", window, BBOX, [])
    assert res.skipped and res.status == "pominięte"


def test_mapillary_tiles_and_parse(window):
    def handler(url, p, h):
        assert h["Authorization"] == "OAuth MLY|x|y"
        assert p["start_captured_at"] == "2026-10-17T13:45:00Z"
        if p["bbox"].startswith("18.960000,50.260000"):
            return {"data": [{"id": "999", "captured_at": 1760712300000, "is_pano": False,
                              "computed_geometry": {"type": "Point", "coordinates": [18.9655, 50.2655]},
                              "thumb_256_url": "https://scontent/x.jpg", "creator": {"username": "jan"}}]}
        return {"data": []}

    http = FakeHttp(handler)
    res = mapillary.search(http, "MLY|x|y", window, BBOX)
    assert len(http.calls) == 24
    (item,) = res.items
    assert item.taken_at.astimezone(TZ).strftime("%H:%M") == "16:45"
    assert (item.lat, item.lon) == (50.2655, 18.9655)
    assert item.url.startswith("https://www.mapillary.com/app/?pKey=999")


def test_mapillary_stops_on_auth_error(window):
    def handler(url, p, h):
        raise HttpError("HTTP 401", status=401, payload={"error": {"message": "Invalid OAuth access token."}})

    http = FakeHttp(handler)
    res = mapillary.search(http, "bad", window, BBOX)
    assert len(http.calls) == 1 and "Invalid OAuth" in res.errors[0]


def test_youtube_scoring(window):
    place, date_score, _ = youtube.score_text("Spacer po Parku Śląskim", "sobota 17.10.2026 Chorzów", window.day)
    assert place == 5 and date_score == 3
    place, _, _ = youtube.score_text("Best of Warsaw", "vlog", window.day)
    assert place == 0


def test_youtube_flow_filters_and_live(window):
    def handler(url, p, h):
        if url == youtube.SEARCH:
            assert p["publishedAfter"] == "2026-10-17T14:15:00Z"
            return {"items": [{"id": {"videoId": "AAA"}}, {"id": {"videoId": "BBB"}}, {"id": {"videoId": "CCC"}}]}
        return {"items": [
            {"id": "AAA", "snippet": {"title": "Legendia 17 października", "description": "", "channelTitle": "x",
                                      "publishedAt": "2026-10-18T10:00:00Z"},
             "recordingDetails": {"recordingDate": "2026-10-17T00:00:00Z"}},
            {"id": "BBB", "snippet": {"title": "Gotowanie makaronu", "description": "", "publishedAt": "2026-10-18T10:00:00Z"}},
            {"id": "CCC", "snippet": {"title": "LIVE Stadion Śląski", "description": "", "publishedAt": "2026-10-17T13:00:00Z"},
             "liveStreamingDetails": {"actualStartTime": "2026-10-17T13:00:00Z", "actualEndTime": "2026-10-17T14:30:00Z"}},
        ]}

    res = youtube.search(FakeHttp(handler), "KEY", window, ["Park Śląski"], pages=1)
    by_id = {i.source_id: i for i in res.items}
    assert set(by_id) == {"AAA", "CCC"}
    assert by_id["AAA"].time_kind == "recording_date" and by_id["AAA"].score >= 10
    live = by_id["CCC"]
    live.finalize(window, None)
    assert live.time_kind == "live" and live.window_status == "in"


def test_youtube_quota_error_stops(window):
    def handler(url, p, h):
        raise HttpError("HTTP 403", status=403,
                        payload={"error": {"code": 403, "message": "quota", "errors": [{"reason": "quotaExceeded"}]}})

    http = FakeHttp(handler)
    res = youtube.search(http, "KEY", window, ["a", "b", "c"], pages=2)
    assert len(http.calls) == 1 and "quotaExceeded" in res.errors[0]


def _page(pageid, dto, lat=None):
    p = {"pageid": pageid, "title": f"File:{pageid}.jpg", "imageinfo": [{
        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{pageid}.jpg",
        "thumburl": "https://upload.wikimedia.org/t.jpg", "timestamp": "2026-10-19T08:00:00Z", "user": "U",
        "extmetadata": {"DateTimeOriginal": {"value": dto}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}
    if lat:
        p["coordinates"] = [{"lat": lat, "lon": 18.99}]
    return p


def test_commons_parse_file_filters_by_day(window):
    assert commons.parse_file(_page(1, "2026-10-17 16:30:00", 50.28), window).time_kind == "exif"
    assert commons.parse_file(_page(2, "2026-10-16 16:30:00"), window) is None
    date_only = commons.parse_file(_page(3, "2026-10-17"), window)
    assert date_only.time_kind == "date_only" and date_only.taken_at is None
    assert commons.parse_file(_page(4, ""), window) is None
    html = commons.parse_file(_page(5, '<time class="dtstart" datetime="2026-10-17">17 października 2026</time> 17:10:00'), window)
    assert html is not None


def test_commons_search_flow(window):
    def handler(url, p, h):
        if p.get("prop") == "categoryinfo":
            return {"query": {"pages": [{"title": "Category:Park Śląski"}, {"title": "Category:Silesian Park", "missing": True}]}}
        if p.get("list") == "search":
            return {"query": {"search": []}}
        if p.get("list") == "categorymembers":
            return {"query": {"categorymembers": []}}
        if p.get("generator") == "categorymembers":
            assert p["gcmstart"] == "2026-10-16T22:00:00Z"
            return {"query": {"pages": [_page(10, "2026-10-17 17:00:00", 50.27), _page(11, "2025-05-01 10:00:00")]}}
        if p.get("generator") == "search":
            return {"query": {"pages": [_page(10, "2026-10-17 17:00:00", 50.27)]}}
        raise AssertionError(p)

    res = commons.search(FakeHttp(handler), window, BBOX, ["Park Śląski", "Silesian Park"], depth=1)
    assert [i.source_id for i in res.items] == ["10"]
    assert res.errors == []


def test_event_snippets(window):
    html = "<div><h3>Sobota</h3><p>17 października 2026, godz. 17:00: koncert w Planetarium</p><p>17.10.2025 stare</p></div>"
    snips = find_snippets(html, window.day)
    assert snips and "koncert w planetarium" in snips[0]
    assert find_snippets("<p>Nic tu nie ma 18.10</p>", window.day) == []


def test_sources_stop_on_blocked_host(window):
    def handler(url, p, h):
        raise HttpError("Połączenie zablokowane", blocked=True)

    for run in (lambda http: mapillary.search(http, "MLY|x", window, BBOX),
                lambda http: flickr.search(http, "KEY", window, BBOX, ["a", "b"]),
                lambda http: youtube.search(http, "KEY", window, ["a", "b"]),
                lambda http: commons.search(http, window, BBOX, ["Park Śląski"])):
        http = FakeHttp(handler)
        res = run(http)
        assert len(http.calls) == 1 and len(res.errors) == 1
