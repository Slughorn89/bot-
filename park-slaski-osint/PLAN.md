# Plan: park-slaski-osint

Cel: zebrać w jednym raporcie PUBLICZNIE dostępne zdjęcia i nagrania z Parku Śląskiego
w Chorzowie z soboty 17.10.2026, okno 16:05 do 17:30 czasu Europe/Warsaw (pierwotnie 16:15 do 18:00, zawężone do czasu spaceru).

## Fakty, które wpływają na kod

| Fakt | Konsekwencja |
|---|---|
| 17.10.2026 to sobota, obowiązuje jeszcze czas letni CEST (UTC+2, zmiana dopiero 25.10.2026) | okno w UTC to 14:05 do 15:30 |
| Zachód słońca w Chorzowie ok. 17:49 CEST | końcówka okna to zmierzch, mniej zdjęć i prawie zero Mapillary po 17:30 |
| Flickr i EXIF zapisują czas "lokalny aparatu" bez strefy | czasy bez strefy traktujemy jako Europe/Warsaw; domyślny margines zapytań 30 min, bo zegary aparatów się rozjeżdżają (aparat bez zmiany czasu na letni pokaże godzinę mniej, wtedy `--margin 75`) |
| YouTube nie ma czasu wykonania, tylko publikację (czasem `recordingDate` albo start transmisji live) | filtrujemy po treści tytułu i opisu, w raporcie oznaczamy, skąd jest czas |
| Mapillary nie lubi dużych bbox | dzielimy bbox parku na kafelki 0,01° |
| robots.txt dotyczy crawlerów, a oficjalne API mają własne regulaminy (Wikimedia wprost zachęca do API mimo `Disallow: /w/` w robots.txt) | robots.txt sprawdzamy przy każdym pobraniu zwykłej strony WWW (wydarzenia), API wołamy zgodnie z ich limitami |

## Podproblemy i podejście

1. **Flickr** (`flickr.photos.search`): zapytanie geo z `bbox` + `min_taken_date`/`max_taken_date`,
   plus zapytania tekstowe bez bbox (Chorzów, Park Śląski, Stadion Śląski, Legendia), żeby złapać
   zdjęcia bez geotagu. Dla każdego trafienia `flickr.photos.getExif` (jeśli autor udostępnia EXIF).
   Limit Flickra: 3600 zapytań/h, my robimy max 1/s.
2. **Mapillary v4** (`/images`): kafelki bbox, `start_captured_at`/`end_captured_at` w UTC,
   `captured_at` to czas z urządzenia (odpowiednik EXIF).
3. **YouTube Data API v3**: `search.list` po frazach z `publishedAfter=2026-10-17T14:05:00Z`,
   potem `videos.list` (recordingDetails, liveStreamingDetails) i filtr po tytule/opisie:
   wymagana fraza miejsca, punkty za wzmiankę o dacie. Pilnujemy kwoty (search = 100 jednostek).
4. **Wikimedia Commons**: kategorie parku (rekurencyjnie, z podkategoriami) z plikami dodanymi
   po 17.10, wyszukiwanie w `Photographs taken on 2026-10-17` zawężone do Chorzowa, opcjonalnie
   skan geosearch bbox. Data wykonania z EXIF (`DateTimeOriginal`).
5. **Linki do ręcznego sprawdzenia**: Instagram (lokalizacja i hashtagi), TikTok, X (`since`/`until`
   oraz `since_time`/`until_time`), Google Maps (zdjęcia miejsc), Facebook, galerie lokalnych mediów.
   Zero scrapowania i logowania, tylko gotowe URL-e do kliknięcia.
6. **Wydarzenia**: lista ustaleń z researchu (z poziomem pewności) + opcjonalne pobranie publicznych
   stron obiektów (z robots.txt i limitem) i wyszukanie na nich wzmianek o 17.10.
7. **Kamery internetowe**: Windy Webcams API (oficjalne, z kluczem) w promieniu parku, info
   o archiwum/timelapse, plus lista katalogów kamer do ręcznego sprawdzenia.
8. **Raport**: `output/report.html` z miniaturami, linkiem, czasem (z oznaczeniem EXIF / API / publikacja),
   odległością od podanego punktu (`--point LAT,LON`), sortowanie po czasie. Do tego `results.json` i `results.csv`.
9. **Trasa spaceru** (GPX/TCX/GeoJSON albo punkty ręcznie): odległość zdjęcia od trasy i od miejsca,
   w którym użytkownik był w chwili zdjęcia; obszar wyszukiwania zawężony do trasy z zapasem.
10. **Pisma**: `letters/` z szablonami: wniosek o zabezpieczenie nagrań (art. 18 ust. 1 lit. c RODO)
   i wniosek o kopię nagrania (art. 15 ust. 3 RODO), plus skrypt do wypełnienia z pliku YAML.

## Granice (czego narzędzie NIE robi)

* nie loguje się nigdzie, nie omija logowania ani paywalli, nie scrapuje Instagrama/TikToka/X/Facebooka,
* nie używa Tora ani darkwebu,
* nie rozpoznaje twarzy ani nie identyfikuje osób trzecich, nie ma żadnej analizy obrazu,
* pobiera tylko miniatury wskazane przez API, pełne pliki zostają u źródła.

## Testy

* testy jednostkowe na zapisanych przykładowych odpowiedziach API (format zgodny z dokumentacją),
* `python -m parkosint doctor`: sprawdza klucze i dostępność hostów,
* przebieg na prawdziwych zapytaniach: `python -m parkosint run --point ...`.
