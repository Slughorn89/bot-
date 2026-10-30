from datetime import datetime

from parkosint import __main__ as cli
from parkosint import route as route_mod
from parkosint.models import Item
from parkosint.timeutil import TZ

GPX = """<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
<trkpt lat="50.2800" lon="18.9900"><time>2026-10-17T14:20:00Z</time></trkpt>
<trkpt lat="50.2750" lon="18.9900"><time>2026-10-17T14:30:00Z</time></trkpt>
<trkpt lat="50.2750" lon="18.9950"><time>2026-10-17T14:40:00Z</time></trkpt>
</trkseg></trk></gpx>"""


def test_gpx_load_distance_and_position(tmp_path):
    f = tmp_path / "spacer.gpx"
    f.write_text(GPX, encoding="utf-8")
    r = route_mod.load(f)
    assert r.timed and len(r.points) == 3
    assert 900 < r.length_m() < 920  # ok. 556 m + 356 m
    # punkt 50 m na wschód od pierwszego odcinka
    assert 45 < r.distance_m(50.2775, 18.9907) < 55
    # 16:25 czasu polskiego = połowa pierwszego odcinka
    lat, lon = r.position_at(datetime(2026, 10, 17, 16, 25, tzinfo=TZ))
    assert abs(lat - 50.2775) < 1e-6 and abs(lon - 18.99) < 1e-6
    assert r.position_at(datetime(2026, 10, 17, 17, 0, tzinfo=TZ)) is None
    b = r.bbox(300)
    assert b.min_lat < 50.2750 - 0.0026 and b.max_lon > 18.9950 + 0.004


def test_manual_points_with_times():
    r = route_mod.parse_points("50.2800,18.9900; 50.2750,18.9900; 50.2750,18.9950")
    assert not r.timed
    t = r.with_times(datetime(2026, 10, 17, 16, 20, tzinfo=TZ), datetime(2026, 10, 17, 16, 40, tzinfo=TZ))
    assert t.timed and t.approx_times
    mid = t.points[1].time.astimezone(TZ)
    assert mid.hour == 16 and 31 <= mid.minute <= 32  # 556/912 drogi


def test_geojson_linestring(tmp_path):
    f = tmp_path / "trasa.geojson"
    f.write_text('{"type":"Feature","geometry":{"type":"LineString","coordinates":[[18.99,50.28],[18.99,50.275]]}}')
    r = route_mod.load(f)
    assert (r.points[0].lat, r.points[0].lon) == (50.28, 18.99)


def test_item_distance_to_you(window, tmp_path):
    f = tmp_path / "spacer.gpx"
    f.write_text(GPX, encoding="utf-8")
    r = route_mod.load(f)
    item = Item("flickr", "1", "u", taken_at=datetime(2026, 10, 17, 16, 25, tzinfo=TZ), time_kind="exif",
                lat=50.2775, lon=18.9907)
    item.finalize(window, (50.2795, 18.9902), r)
    assert 45 < item.dist_route_m < 55 and 45 < item.dist_you_m < 55
    pub = Item("youtube", "2", "u", published_at=datetime(2026, 10, 17, 16, 25, tzinfo=TZ), time_kind="published",
               lat=50.2775, lon=18.9907)
    pub.finalize(window, None, r)
    assert pub.dist_you_m is None  # czas publikacji nie mówi, gdzie wtedy byłeś


def test_cli_with_route_points(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTE_FILE", "")
    rc = cli.main(["run", "--sources", "none", "--no-pages", "--out", str(tmp_path),
                   "--route-points", "50.2800,18.9900; 50.2750,18.9900", "--route-start", "16:20", "--route-end", "16:40"])
    assert rc == 0
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "punkty wpisane ręcznie" in html and "czasy przybliżone" in html and "od trasy" in html


def test_timetable_aligned_to_step():
    r = route_mod.parse_points("50.2800,18.9900; 50.2750,18.9900").with_times(
        datetime(2026, 10, 17, 16, 5, tzinfo=TZ), datetime(2026, 10, 17, 16, 32, tzinfo=TZ))
    times = [t.astimezone(TZ).strftime("%H:%M") for t, _, _ in r.timetable(10)]
    assert times == ["16:05", "16:10", "16:20", "16:30", "16:32"]


def test_cli_uses_route_start_as_reference_point(tmp_path, monkeypatch):
    for k in ("ROUTE_FILE", "REFERENCE_POINT", "ROUTE_START", "ROUTE_END"):
        monkeypatch.setenv(k, "")
    rc = cli.main(["run", "--sources", "none", "--no-pages", "--out", str(tmp_path),
                   "--route-points", "50.2880,18.9800; 50.2850,18.9850", "--route-start", "16:05", "--route-end", "16:35"])
    assert rc == 0
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Punkt odniesienia (start trasy)" in html and "50.288000, 18.980000" in html
    assert "Gdzie byłeś o której" in html and "w oknie 16:05 do 17:30" in html
