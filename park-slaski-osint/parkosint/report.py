from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import __version__
from .geo import BBox, fmt_distance
from .http import Http
from .models import TIME_KINDS, Item, SourceResult
from .timeutil import TZ, Window, fmt_local

log = logging.getLogger(__name__)

TEMPLATES = Path(__file__).resolve().parent / "templates"
FAR = datetime.max.replace(tzinfo=TZ)


def sort_items(items: list[Item]) -> list[Item]:
    return sorted(items, key=lambda i: (i.sort_time or FAR, i.source, i.source_id))


def download_thumbs(http: Http, items: list[Item], out_dir: Path) -> None:
    thumbs = out_dir / "thumbs"
    for item in items:
        if not item.thumb_url:
            continue
        path = thumbs / f"{item.source}_{item.source_id}.jpg"
        if path.exists() or http.download(item.thumb_url, path):
            item.local_thumb = f"thumbs/{path.name}"


def write_exports(out_dir: Path, items: list[Item]) -> None:
    rows = [i.to_dict() for i in items]
    (out_dir / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    cols = ["taken_at", "time_kind_label", "window_status", "source", "title", "author", "url",
            "distance_m", "dist_route_m", "dist_you_m", "lat", "lon", "published_at", "media_type", "license", "notes"]
    with open(out_dir / "results.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", delimiter=";")
        w.writeheader()
        for r in rows:
            r["notes"] = " | ".join(r["notes"])
            w.writerow(r)


def _route_line(route, max_points: int = 1500) -> list[list[float]]:
    if route is None:
        return []
    step = max(1, len(route.points) // max_points)
    pts = route.points[::step] + ([route.points[-1]] if (len(route.points) - 1) % step else [])
    return [[round(p.lat, 6), round(p.lon, 6)] for p in pts]


def render(out_dir: Path, window: Window, point, bbox: BBox, results: list[SourceResult],
           events, webcams, link_groups, today, route=None) -> Path:
    items = sort_items([i for r in results for i in r.items])
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    env.filters["local"] = fmt_local
    env.filters["dist"] = fmt_distance
    map_points = [
        {"lat": i.lat, "lon": i.lon, "title": i.title[:80], "url": i.url, "source": i.source,
         "time": fmt_local(i.sort_time), "in": i.window_status == "in"}
        for i in items if i.lat is not None and i.lon is not None
    ]
    html = env.get_template("report.html.j2").render(
        window=window, point=point, bbox=bbox, results=results, items=items,
        time_kinds=TIME_KINDS, events=events, webcams=webcams, link_groups=link_groups,
        generated=datetime.now(TZ), today=today, version=__version__,
        map_points=json.dumps(map_points, ensure_ascii=False),
        route=route,
        route_line=json.dumps(_route_line(route)),
        in_window=sum(1 for i in items if i.window_status == "in"),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "report.html"
    path.write_text(html, encoding="utf-8")
    write_exports(out_dir, items)
    return path
