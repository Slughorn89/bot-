from datetime import datetime, timezone

from parkosint.geo import BBox, fmt_distance, haversine_m, parse_point
from parkosint.http import redact
from parkosint.letters import fill
from parkosint.textutil import date_patterns, fold
from parkosint.timeutil import TZ, local_naive_str, parse_local, utc_iso


def test_window_is_cest_and_converts_to_utc(window):
    assert window.start.tzname() == "CEST"
    assert utc_iso(window.start) == "2026-10-17T14:15:00Z"
    assert utc_iso(window.end) == "2026-10-17T16:00:00Z"
    assert local_naive_str(window.query_start) == "2026-10-17 15:45:00"
    assert local_naive_str(window.query_end) == "2026-10-17 18:30:00"


def test_window_classify(window):
    assert window.classify(datetime(2026, 10, 17, 17, 0, tzinfo=TZ)) == "in"
    assert window.classify(datetime(2026, 10, 17, 15, 50, tzinfo=TZ)) == "margin"
    assert window.classify(datetime(2026, 10, 17, 12, 0, tzinfo=TZ)) == "out"
    assert window.classify(None) is None
    # transmisja 15:00 do 16:30 nachodzi na okno
    assert window.classify_range(datetime(2026, 10, 17, 15, 0, tzinfo=TZ), datetime(2026, 10, 17, 16, 30, tzinfo=TZ)) == "in"


def test_parse_local_exif_and_offset():
    dt = parse_local("2026:10:17 16:20:11")
    assert dt.tzinfo == TZ and dt.hour == 16
    assert dt.astimezone(timezone.utc).hour == 14
    dt2 = parse_local("2026:10:17 15:20:11", "+01:00")  # aparat w czasie zimowym
    assert dt2.astimezone(TZ).hour == 16
    assert parse_local("2026-10-17T14:20:11Z").astimezone(TZ).hour == 16
    assert parse_local("bzdura") is None


def test_bbox_tiles_and_formats():
    b = BBox.parse("50.2600,18.9600,50.2960,19.0150")
    tiles = b.tiles(0.01)
    assert len(tiles) == 4 * 6
    assert tiles[0].min_lat == b.min_lat and tiles[-1].max_lon == b.max_lon
    assert b.lon_lat_str() == "18.960000,50.260000,19.015000,50.296000"
    assert b.mediawiki_str() == "50.296000|18.960000|50.260000|19.015000"


def test_distance():
    d = haversine_m(50.0, 19.0, 50.001, 19.0)
    assert 110 < d < 112
    assert fmt_distance(None) == "brak geolokalizacji"
    assert fmt_distance(1234) == "1,23 km"
    assert parse_point("50.279, 18.989") == (50.279, 18.989)


def test_fold_and_date_patterns(window):
    assert fold("Park ŚLĄSKI, Łódź") == "park slaski, lodz"
    pats = date_patterns(window.day)
    hits = lambda s: any(p.search(fold(s)) for p in pats)  # noqa: E731
    assert hits("Sobota, 17 października 2026")
    assert hits("Spacer 17.10.2026")
    assert hits("vlog 17.10")
    assert hits("2026-10-17 park")
    assert not hits("Spacer 17.10.2025")
    assert not hits("18 października")


def test_redact_hides_keys():
    s = redact("https://x/?api_key=SECRET&key=ABC&access_token=MLY|1|2&q=park")
    assert "SECRET" not in s and "ABC" not in s and "MLY" not in s and "q=park" in s


def test_letters_fill_missing_and_empty():
    text, missing = fill("A {{IMIE}} B{{OPCJA}} C {{BRAK}}", {"IMIE": "Jan", "OPCJA": ""})
    assert text == "A Jan B C [BRAK]"
    assert missing == ["BRAK"]


def test_robots_rules_crawl_delay_and_unreachable(monkeypatch):
    from parkosint.http import Http, HttpError

    class Resp:
        def __init__(self, code, text=""):
            self.status_code, self.text, self.headers = code, text, {}

    def fake_request(url, params=None, headers=None, robots=False):
        if "blocked.example" in url:
            raise HttpError("zablokowane", blocked=True)
        if "nofile.example" in url:
            return Resp(404)
        return Resp(200, "User-agent: *\nDisallow: /private\nCrawl-delay: 3\n")

    http = Http(sleep=lambda s: None)
    monkeypatch.setattr(http, "request", fake_request)
    assert http.allowed_by_robots("https://ok.example/kalendarz")
    assert not http.allowed_by_robots("https://ok.example/private/x")
    assert http.per_host["ok.example"] == 3
    assert http.allowed_by_robots("https://nofile.example/x")
    assert not http.allowed_by_robots("https://blocked.example/x")
    assert "robots.txt" in http._robots_reason["https://blocked.example"]


def test_default_point_and_env_override(monkeypatch, tmp_path):
    from parkosint.config import DEFAULT_POINT, Settings

    monkeypatch.setenv("REFERENCE_POINT", "")
    assert Settings.from_env(tmp_path / "brak.env").point == DEFAULT_POINT == (50.2795, 18.9902)
    monkeypatch.setenv("REFERENCE_POINT", "50.28,18.99")
    assert Settings.from_env(tmp_path / "brak.env").point == (50.28, 18.99)
