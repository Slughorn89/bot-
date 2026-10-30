"""CLI: python -m parkosint {run,links,doctor,letters}"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, time
from pathlib import Path

from . import keys, letters, links, report
from . import route as route_mod
from .config import (COMMONS_CATEGORIES, DEFAULT_DATE, DEFAULT_END, DEFAULT_START, FLICKR_TEXT_QUERIES, ROOT,
                     YOUTUBE_PHRASES, Settings)
from .geo import parse_point
from .http import Http, HttpError
from .models import PRECISE_TIME
from .sources import commons, events, flickr, mapillary, webcams, youtube
from .timeutil import TZ, Window

log = logging.getLogger("parkosint")
ALL_SOURCES = "flickr,mapillary,youtube,commons,events,webcams"


def _window(args) -> Window:
    return Window.from_local(date.fromisoformat(args.date), time.fromisoformat(args.start),
                             time.fromisoformat(args.end), args.margin)


def _point(args, settings: Settings):
    return parse_point(args.point) if args.point else settings.point


def _route(args, settings: Settings, window: Window):
    if args.route_points:
        route = route_mod.parse_points(args.route_points)
    elif args.route or settings.route_file:
        route = route_mod.load(Path(args.route or settings.route_file))
    else:
        return None
    if not route.timed and args.route_start and args.route_end:
        route = route.with_times(datetime.combine(window.day, time.fromisoformat(args.route_start), TZ),
                                 datetime.combine(window.day, time.fromisoformat(args.route_end), TZ))
    info = f"Trasa: {route.source}, {len(route.points)} punktów, {route.length_m() / 1000:.2f} km"
    if route.timed:
        info += f", {route.start.astimezone(TZ):%d.%m %H:%M} do {route.end.astimezone(TZ):%H:%M}"
        if route.approx_times:
            info += " (czasy przybliżone, stałe tempo)"
        if route.end < window.start or route.start > window.end:
            log.warning("Czas trasy nie nachodzi na okno %s, sprawdź --start/--end", window.label())
    log.info(info)
    return route


def cmd_run(args) -> int:
    settings = Settings.from_env()
    window = _window(args)
    point = _point(args, settings)
    route = _route(args, settings, window)
    bbox = route.bbox(args.route_buffer) if route and not args.whole_park else settings.bbox
    selected = {s.strip() for s in args.sources.split(",") if s.strip()}
    http = Http(contact=settings.contact, default_interval=args.interval)
    out = Path(args.out)
    log.info("Okno: %s, punkt: %s", window.label(), point or "brak")

    results = []
    if "flickr" in selected:
        log.info("Flickr...")
        results.append(flickr.search(http, settings.flickr_key, window, bbox, FLICKR_TEXT_QUERIES,
                                     fetch_exif=not args.no_exif))
    if "mapillary" in selected:
        log.info("Mapillary...")
        results.append(mapillary.search(http, settings.mapillary_token, window, bbox, tile=args.mapillary_tile))
    if "youtube" in selected:
        log.info("YouTube...")
        results.append(youtube.search(http, settings.youtube_key, window, YOUTUBE_PHRASES, pages=args.yt_pages))
    if "commons" in selected:
        log.info("Wikimedia Commons...")
        results.append(commons.search(http, window, bbox, COMMONS_CATEGORIES, geo_scan=args.commons_geo_scan))

    for r in results:
        for item in r.items:
            item.finalize(window, point, route)
        if not args.keep_out:
            before = len(r.items)
            r.items = [i for i in r.items if not (i.window_status == "out" and i.time_kind in PRECISE_TIME)]
            if before != len(r.items):
                r.notes.append(f"odrzucono {before - len(r.items)} wyników spoza okna z marginesem (--keep-out zostawia)")

    log.info("Wydarzenia...")
    ev = events.collect(http if "events" in selected else None, window.day, fetch_pages=not args.no_pages)
    if "webcams" in selected:
        log.info("Kamery...")
        cams = webcams.search(http, settings.windy_key, bbox.center, point)
    else:
        cams = webcams.WebcamResult(skipped="wyłączone w --sources")
    groups = links.build(window, bbox.center, point, settings.instagram_location_ids)

    all_items = [i for r in results for i in r.items]
    if not args.no_thumbs and all_items:
        log.info("Miniatury (%d)...", len(all_items))
        report.download_thumbs(http, all_items, out)
    path = report.render(out, window, point, bbox, results, ev, cams, groups, today=datetime.now(TZ).date(),
                         route=route)

    print(f"\nRaport: {path}")
    for r in results:
        line = f"  {r.name:10s} {r.status:10s} wyników: {len(r.items)}"
        if r.skipped:
            line += f"  ({r.skipped})"
        print(line)
        for e in r.errors[:3]:
            print(f"      ! {e[:200]}")
    print(f"  zapytań HTTP: {http.count}")
    return 0


def cmd_links(args) -> int:
    settings = Settings.from_env()
    window = _window(args)
    for g in links.build(window, settings.bbox.center, _point(args, settings), settings.instagram_location_ids):
        print(f"\n## {g.name}\n{g.note}")
        for label, url in g.links:
            print(f"- {label}: {url}")
    return 0


def cmd_doctor(args) -> int:
    settings = Settings.from_env()
    http = Http(contact=settings.contact, max_retries=0, timeout=15)
    keys = {
        "FLICKR_API_KEY": settings.flickr_key, "MAPILLARY_ACCESS_TOKEN": settings.mapillary_token,
        "YOUTUBE_API_KEY": settings.youtube_key, "WINDY_WEBCAMS_API_KEY": settings.windy_key,
        "CONTACT_EMAIL": settings.contact,
    }
    print("Klucze w .env:")
    for k, v in keys.items():
        print(f"  {k:24s} {'ustawiony' if v else 'BRAK'}")
    print(f"  REFERENCE_POINT          {settings.point[0]}, {settings.point[1]}")
    checks = [
        ("Flickr", "https://api.flickr.com/services/rest/",
         {"method": "flickr.test.echo", "api_key": settings.flickr_key, "format": "json", "nojsoncallback": 1}, None),
        ("Mapillary", "https://graph.mapillary.com/images",
         {"bbox": "18.985,50.278,18.986,50.279", "limit": 1, "fields": "id"},
         {"Authorization": f"OAuth {settings.mapillary_token}"}),
        ("YouTube", "https://www.googleapis.com/youtube/v3/videos",
         {"part": "id", "id": "jNQXAC9IVRw", "key": settings.youtube_key}, None),
        ("Wikimedia Commons", "https://commons.wikimedia.org/w/api.php",
         {"action": "query", "meta": "siteinfo", "format": "json"}, None),
        ("Windy Webcams", "https://api.windy.com/webcams/api/v3/webcams",
         {"limit": 1}, {"x-windy-api-key": settings.windy_key}),
    ]
    print("\nPołączenia:")
    ok = True
    for name, url, params, headers in checks:
        try:
            r = http.request(url, params=params, headers=headers)
            verdict = "OK" if r.status_code == 200 else f"HTTP {r.status_code} (host osiągalny, sprawdź klucz)"
            if r.status_code != 200:
                ok = False
        except HttpError as e:
            verdict, ok = f"NIEOSIĄGALNY: {e}", False
        print(f"  {name:18s} {verdict[:160]}")
    return 0 if ok else 1


def cmd_keys(args) -> int:
    settings = Settings.from_env()
    http = Http(contact=settings.contact, max_retries=0, timeout=20)
    services = [s.strip() for s in args.only.split(",") if s.strip()]
    saved = keys.run_wizard(services, http, open_browser=not args.no_browser, use_gcloud=not args.no_gcloud)
    return 0 if saved else 1


def cmd_letters(args) -> int:
    written = letters.render_all(Path(args.data), Path(args.out))
    for path, missing in written:
        print(f"{path}" + (f"  (do uzupełnienia: {', '.join(missing)})" if missing else ""))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="parkosint", description="Publiczne zdjęcia i nagrania z Parku Śląskiego")
    sub = p.add_subparsers(dest="cmd", required=True)

    def window_args(sp):
        sp.add_argument("--date", default=DEFAULT_DATE.isoformat(), help="RRRR-MM-DD (domyślnie %(default)s)")
        sp.add_argument("--start", default=DEFAULT_START.strftime("%H:%M"), help="początek okna, czas Warszawy")
        sp.add_argument("--end", default=DEFAULT_END.strftime("%H:%M"), help="koniec okna, czas Warszawy")
        sp.add_argument("--margin", type=int, default=30, help="margines zapytań w minutach (zegary aparatów się mylą)")
        sp.add_argument("--point", help="punkt odniesienia 'lat,lon' (domyślnie 50.2795,18.9902)")

    run = sub.add_parser("run", help="przeszukaj źródła i zbuduj report.html")
    window_args(run)
    run.add_argument("--sources", default=ALL_SOURCES, help="lista po przecinku (domyślnie wszystkie)")
    run.add_argument("--out", default=str(ROOT / "output"))
    run.add_argument("--interval", type=float, default=1.0, help="min. odstęp między zapytaniami do jednego hosta [s]")
    run.add_argument("--no-thumbs", action="store_true", help="nie pobieraj miniatur (raport użyje zdalnych URL-i)")
    run.add_argument("--no-exif", action="store_true", help="nie pytaj Flickra o EXIF")
    run.add_argument("--no-pages", action="store_true", help="nie pobieraj stron obiektów przy wydarzeniach")
    run.add_argument("--keep-out", action="store_true", help="zostaw wyniki z dokładnym czasem spoza okna")
    run.add_argument("--yt-pages", type=int, default=2, help="strony wyników na frazę (100 jednostek kwoty każda)")
    run.add_argument("--mapillary-tile", type=float, default=0.01, help="bok kafelka bbox w stopniach")
    run.add_argument("--commons-geo-scan", action="store_true", help="dodatkowy skan geosearch Commons (wolniejszy)")
    run.add_argument("--route", help="plik trasy: GPX, TCX, GeoJSON albo .txt z punktami (albo ROUTE_FILE w .env)")
    run.add_argument("--route-points", help="trasa jako punkty 'lat,lon; lat,lon; ...' (np. z Google Maps)")
    run.add_argument("--route-start", help="godzina startu spaceru HH:MM, gdy trasa nie ma czasów")
    run.add_argument("--route-end", help="godzina końca spaceru HH:MM, gdy trasa nie ma czasów")
    run.add_argument("--route-buffer", type=float, default=300, help="ile metrów wokół trasy przeszukiwać")
    run.add_argument("--whole-park", action="store_true", help="przeszukuj cały park mimo podanej trasy")
    run.set_defaults(func=cmd_run)

    lk = sub.add_parser("links", help="wypisz linki do ręcznego sprawdzenia")
    window_args(lk)
    lk.set_defaults(func=cmd_links)

    dr = sub.add_parser("doctor", help="sprawdź klucze i dostęp do API")
    dr.set_defaults(func=cmd_doctor)

    ks = sub.add_parser("keys", help="kreator kluczy API (YouTube automatycznie przez gcloud)")
    ks.add_argument("--only", default="youtube,mapillary,flickr,windy", help="które klucze (po przecinku)")
    ks.add_argument("--no-browser", action="store_true", help="nie otwieraj stron w przeglądarce")
    ks.add_argument("--no-gcloud", action="store_true", help="YouTube też ręcznie, bez gcloud")
    ks.set_defaults(func=cmd_keys)

    lt = sub.add_parser("letters", help="wypełnij szablony pism danymi z pliku YAML")
    lt.add_argument("--data", default=str(ROOT / "letters" / "dane.yaml"))
    lt.add_argument("--out", default=str(ROOT / "output" / "letters"))
    lt.set_defaults(func=cmd_letters)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
