"""Gotowe linki do RĘCZNEGO sprawdzenia w przeglądarce. Narzędzie ich nie otwiera,
nie scrapuje tych serwisów i nigdzie się nie loguje."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import quote, quote_plus, urlencode

from .config import INSTAGRAM_TAGS, POIS
from .timeutil import Window


@dataclass
class LinkGroup:
    name: str
    note: str
    links: list[tuple[str, str]] = field(default_factory=list)


def _google(q: str, window: Window | None = None, days_after: int = 14) -> str:
    params = {"q": q, "hl": "pl"}
    if window:
        d0 = window.day
        d1 = d0 + timedelta(days=days_after)
        params["tbs"] = f"cdr:1,cd_min:{d0:%m/%d/%Y},cd_max:{d1:%m/%d/%Y}"
    return "https://www.google.com/search?" + urlencode(params)


def x_queries(window: Window, center: tuple[float, float]) -> list[tuple[str, str]]:
    day, nxt = window.day, window.day + timedelta(days=1)
    t0, t1 = int(window.query_start.timestamp()), int(window.query_end.timestamp())
    names = '("Park Śląski" OR "Parku Śląskim" OR "Stadion Śląski" OR Legendia OR Chorzów OR #ParkŚląski)'
    qs = [
        ("X: słowa kluczowe, cały dzień, tylko media", f"{names} since:{day} until:{nxt} filter:media"),
        ("X: słowa kluczowe, dokładne okno (since_time/until_time)", f"{names} since_time:{t0} until_time:{t1}"),
        ("X: wszystko w promieniu 2 km od parku, dokładne okno", f"geocode:{center[0]:.4f},{center[1]:.4f},2km since_time:{t0} until_time:{t1}"),
        ("X: odpowiedzi i relacje kilka dni później", f"{names} since:{day} until:{day + timedelta(days=4)}"),
    ]
    links = [(label, "https://x.com/search?" + urlencode({"q": q, "src": "typed_query", "f": "live"})) for label, q in qs]
    links.append(("X: oficjalny profil TAURON Park Śląski (@park_slaski)", "https://x.com/park_slaski"))
    return links


def build(window: Window, center: tuple[float, float], point: tuple[float, float] | None,
          instagram_location_ids: list[str] | None = None) -> list[LinkGroup]:
    groups: list[LinkGroup] = []
    lat, lon = point or center
    d = window.day
    date_pl = f"{d.day} października" if d.month == 10 else f"{d:%d.%m}"

    ig = LinkGroup("Instagram", "Instagram zwykle wymaga zalogowania w Twojej przeglądarce. Sortuj po najnowszych i przewiń do posta z 17.10.")
    for loc in instagram_location_ids or []:
        ig.links.append((f"lokalizacja {loc}", f"https://www.instagram.com/explore/locations/{loc}/"))
    ig.links.append(("jak znaleźć ID lokalizacji Park Śląski (Google)",
                     _google('site:instagram.com/explore/locations "Park Śląski"')))
    for tag in INSTAGRAM_TAGS:
        ig.links.append((f"#{tag}", f"https://www.instagram.com/explore/tags/{tag}/"))
    groups.append(ig)

    tt = LinkGroup("TikTok", "Wyszukiwarka TikToka nie ma filtra daty w URL, przeglądaj wyniki ręcznie.")
    for q in ["park śląski", "park śląski chorzów", "stadion śląski", "legendia", f"park śląski {d:%d.%m}"]:
        tt.links.append((f"szukaj: {q}", "https://www.tiktok.com/search/video?q=" + quote(q)))
    for tag in ["parkslaski", "chorzow", "legendia", "stadionslaski"]:
        tt.links.append((f"#{tag}", f"https://www.tiktok.com/tag/{tag}"))
    groups.append(tt)

    groups.append(LinkGroup("X (Twitter)", "Wyszukiwanie na X wymaga zalogowania. since_time/until_time to czas uniksowy okna z marginesem.",
                            x_queries(window, center)))

    gm = LinkGroup("Google Maps (zdjęcia miejsc)",
                   "Na karcie miejsca: Zdjęcia, potem 'Najnowsze' lub 'Od odwiedzających'. W Opiniach: Sortuj, Najnowsze (opinie często mają zdjęcia).")
    for poi in POIS:
        gm.links.append((poi, "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": poi})))
    gm.links.append(("Twój punkt odniesienia", f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}"))
    groups.append(gm)

    fb = LinkGroup("Facebook", "Wymaga zalogowania. Warto przejrzeć grupy mieszkańców Chorzowa i fanpage obiektów (posty z 17 i 18.10).")
    for q in [f"Park Śląski {date_pl}", "Park Śląski Chorzów", f"Legendia {date_pl}"]:
        fb.links.append((f"posty: {q}", "https://www.facebook.com/search/posts/?q=" + quote(q)))
    groups.append(fb)

    media = LinkGroup("Galerie lokalnych mediów (Google z filtrem dat 17.10 do 31.10)",
                      "Lokalne portale często publikują galerie 'ZDJĘCIA' z weekendu w parku.")
    for site in ["dziennikzachodni.pl", "naszemiasto.pl", "tubachorzowa.pl", "wyborcza.pl"]:
        media.links.append((site, _google(f'site:{site} "Park Śląski" zdjęcia', window)))
    media.links.append(("dowolna strona: Park Śląski + data", _google(f'"Park Śląski" "{date_pl}"', window)))
    groups.append(media)

    t0 = int(window.query_start.timestamp())
    t1 = int(window.query_end.timestamp())
    no_key = LinkGroup("Bez kluczy API (te same źródła ręcznie)", "Przydatne, jeśli nie masz jeszcze kluczy API.")
    no_key.links += [
        ("YouTube: Park Śląski, sortowanie po dacie przesłania",
         "https://www.youtube.com/results?search_query=" + quote_plus("Park Śląski") + "&sp=CAI%253D"),
        ("Flickr: Chorzów, zakres daty wykonania",
         "https://www.flickr.com/search/?" + urlencode({"text": "Chorzów", "min_taken_date": t0, "max_taken_date": t1})),
        ("Mapillary: mapa wokół punktu (ustaw filtr dat w panelu)",
         f"https://www.mapillary.com/app/?lat={lat:.6f}&lng={lon:.6f}&z=16"),
        ("Wikimedia Commons: zdjęcia z 17.10.2026",
         "https://commons.wikimedia.org/w/index.php?" + urlencode({"search": f'incategory:"Photographs_taken_on_{d.isoformat()}" Chorzów', "ns6": 1})),
    ]
    groups.append(no_key)

    cams = LinkGroup("Kamery internetowe (ręcznie)",
                     "Jedyna znaleziona publiczna kamera w parku to ta na rzeźbie 'Komar Dron' (al. Ziętka / Leśna), "
                     "kiedyś transmitowana na stronie parku. Sprawdź, czy działa i czy ma archiwum. Park miał też "
                     "monitoring (ok. 40 kamer, m.in. na podporach kolejki Elka), ale ten nie jest publiczny: do niego są pisma.")
    cams.links += [
        ("nocowanie.pl: kamera Park Śląski (katalog zewnętrzny)", "https://kamery.nocowanie.pl/chorzow/31527/"),
        ("Dziennik Zachodni: kamera na Komar Dronie", "https://dziennikzachodni.pl/komar-dron-w-parku-slaskim-pokaze-nam-jaka-jest-pogoda-w-parku-zdjecia/ar/3570547"),
        ("webcams.org.ru: Chorzów", "https://webcams.org.ru/amp/chorzow.htm"),
        ("webcams.org.ru: Katowice", "https://webcams.org.ru/katowice.htm"),
        ("Outdooractive: kamery Katowice", "https://julian-alps.com/en/webcams/katowice/webcams-in-katowice/227980892/"),
        ("Google: kamera na żywo Park Śląski", _google('"Park Śląski" kamera "na żywo" OR webcam OR timelapse')),
        ("Google: webcamera.pl Chorzów", _google("site:webcamera.pl Chorzów OR Katowice")),
        ("Google: skylinewebcams Chorzów/Katowice", _google("site:skylinewebcams.com Katowice OR Chorzów")),
    ]
    groups.append(cams)
    return groups

