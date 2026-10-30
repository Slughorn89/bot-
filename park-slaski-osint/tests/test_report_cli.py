import csv
from datetime import date, datetime
from urllib.parse import parse_qs, urlparse

from parkosint import __main__ as cli
from parkosint import links, report
from parkosint.geo import BBox
from parkosint.models import Item, SourceResult
from parkosint.sources.events import EventsResult
from parkosint.sources.webcams import Webcam, WebcamResult
from parkosint.timeutil import TZ

BBOX = BBox.parse("50.2600,18.9600,50.2960,19.0150")


def test_x_links_use_window_epochs(window):
    groups = {g.name: g for g in links.build(window, BBOX.center, (50.28, 18.99))}
    x = groups["X (Twitter)"].links
    q = parse_qs(urlparse(x[1][1]).query)["q"][0]
    assert f"since_time:{int(window.query_start.timestamp())}" in q
    assert "since:2026-10-17 until:2026-10-18" in parse_qs(urlparse(x[0][1]).query)["q"][0]
    assert all(url.startswith("https://") for g in groups.values() for _, url in g.links)


def test_webcam_archive_note():
    cam = Webcam("1", "Kamera", 50.27, 18.98, "active", "https://x", None, {"day": "u1", "month": "u2"})
    assert "month" in cam.archive_note(date(2026, 10, 17), date(2026, 10, 30))
    assert "nie sięgają" in Webcam("2", "K", None, None, "", "", None, {"day": "u"}).archive_note(date(2026, 10, 17), date(2026, 10, 30))


def test_report_sorted_by_time(tmp_path, window):
    late = Item("flickr", "2", "https://flickr/2", title="Późne <b>", taken_at=datetime(2026, 10, 17, 17, 50, tzinfo=TZ),
                time_kind="exif", lat=50.28, lon=18.99)
    early = Item("mapillary", "1", "https://mly/1", title="Wczesne", taken_at=datetime(2026, 10, 17, 16, 20, tzinfo=TZ),
                 time_kind="device", lat=50.2801, lon=18.9901)
    pub = Item("youtube", "3", "https://yt/3", title="Film", published_at=datetime(2026, 10, 18, 9, 0, tzinfo=TZ),
               time_kind="published")
    for i in (late, early, pub):
        i.finalize(window, (50.28, 18.99))
    results = [SourceResult("flickr", [late]), SourceResult("mapillary", [early]), SourceResult("youtube", [pub], errors=["test"])]
    path = report.render(tmp_path, window, (50.28, 18.99), BBOX, results, EventsResult(), WebcamResult(skipped="brak"),
                         links.build(window, BBOX.center, None), today=date(2026, 10, 30))
    html = path.read_text(encoding="utf-8")
    assert html.index("Wczesne") < html.index("Późne") < html.index("Film")
    assert "Późne &lt;b&gt;" in html  # escapowanie
    assert "w oknie" in html and "czas publikacji, NIE wykonania" in html
    rows = list(csv.DictReader(open(tmp_path / "results.csv", encoding="utf-8-sig"), delimiter=";"))
    assert [r["source"] for r in rows] == ["mapillary", "flickr", "youtube"]
    assert early.distance_m is not None and early.distance_m < 20


def test_cli_run_without_keys_makes_report_offline(tmp_path, monkeypatch):
    for k in ("FLICKR_API_KEY", "MAPILLARY_ACCESS_TOKEN", "YOUTUBE_API_KEY", "WINDY_WEBCAMS_API_KEY", "REFERENCE_POINT"):
        monkeypatch.setenv(k, "")
    rc = cli.main(["run", "--sources", "flickr,mapillary,youtube", "--no-thumbs", "--no-pages",
                   "--point", "50.279,18.989", "--out", str(tmp_path)])
    assert rc == 0
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "brak FLICKR_API_KEY" in html and "Do ręcznego sprawdzenia" in html
    assert "Dzień Planetariów" in html  # ustalenia z researchu
