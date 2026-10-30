# park-slaski-osint

Narzędzie zbiera w jednym raporcie **publiczne** zdjęcia i nagrania z Parku Śląskiego w Chorzowie
z soboty **17.10.2026, 16:15 do 18:00** (Europe/Warsaw). Korzysta tylko z oficjalnych API,
a resztę serwisów daje jako gotowe linki do kliknięcia samemu.

Wynik: `output/report.html` z miniaturami, linkiem do źródła, czasem wykonania (EXIF, jeśli jest),
odległością od Twojego punktu i mapą. Sortowanie po czasie. Do tego `results.csv` i `results.json`.

Plan i założenia: [PLAN.md](PLAN.md). Pisma do administratorów monitoringu: [letters/](letters/README.md).

## Szybki start

```bash
cd park-slaski-osint
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m parkosint keys             # kreator kluczy: YouTube sam, resztę wklejasz (niżej)
python -m parkosint doctor           # sprawdza klucze i połączenia
python -m parkosint run              # punkt odniesienia domyślnie 50.2795, 18.9902
```

Raport otwierasz w przeglądarce: `output/report.html`. Działa bez kluczy (wtedy dostajesz Commons,
wydarzenia i linki ręczne), z każdym kluczem dochodzi kolejne źródło.

## Twoja trasa (największa dokładność)

Z trasą raport pokazuje przy każdym zdjęciu z geotagiem dwie dodatkowe rzeczy: jak daleko było od Twojej
drogi i jak daleko od miejsca, w którym byłeś **dokładnie w chwili zrobienia zdjęcia**. Zdjęcia, przy których
byłeś bliżej niż 150 m, dostają zieloną etykietę. Przeszukiwany obszar zawęża się do trasy z zapasem 300 m.

Pliki z trasą trzymaj w `private/` (jest w `.gitignore`), bo start i koniec spaceru to zwykle okolice domu.
To repozytorium jest publiczne, więc trasy nigdy nie commituj.

**A. Plik GPX/TCX z aplikacji** (najlepiej, bo ma prawdziwe czasy):

```bash
python -m parkosint run --route private/spacer.gpx
```

W szczegółach treningu szukaj *Udostępnij* albo *Eksportuj*, a potem GPX. Strava, Garmin Connect czy Komoot to mają.
Huawei Zdrowie nie ma takiego przycisku, wtedy użyj B albo C.

**B. Punkty wpisane ręcznie z Google Maps** (5 minut roboty):
1. Na mapie przytrzymaj palec na trasie, na górze pojawią się współrzędne. Skopiuj je.
2. Zbierz 6 do 10 punktów po kolei: start, każdy zakręt, nawrotki, koniec.
3. Godzinę startu i końca spaceru odczytasz w szczegółach treningu w aplikacji.

```bash
python -m parkosint run --route-points "50.2795,18.9902; 50.2770,18.9930; ..." --route-start 16:20 --route-end 17:25
```

Program rozłoży czas na trasie przy założeniu stałego tempa, więc „gdzie byłem o 16:47” będzie przybliżone
(zwykle do 100 do 200 m), a odległość od samej trasy będzie dokładna.

**C. Narysuj trasę** na https://geojson.io (narzędzie linii), zapisz jako GeoJSON i podaj `--route private/trasa.geojson`
plus `--route-start` i `--route-end` jak w B.

Na stałe: wpisz `ROUTE_FILE=private/spacer.gpx` w `.env`. Cały park mimo trasy: `--whole-park`.

## Źródła

| # | Źródło | Jak | Klucz |
|---|---|---|---|
| 1 | Flickr | `flickr.photos.search` z bbox parku i `min/max_taken_date`, plus wyszukiwanie tekstowe dla zdjęć bez geotagu, EXIF z `flickr.photos.getExif` | `FLICKR_API_KEY` |
| 2 | Mapillary | API v4 `/images`, bbox w kafelkach 0,01°, `start/end_captured_at` | `MAPILLARY_ACCESS_TOKEN` |
| 3 | YouTube | `search.list` po frazach (Park Śląski, Chorzów, Stadion Śląski, Legendia...) z `publishedAfter`, potem `videos.list` i filtr po tytule i opisie | `YOUTUBE_API_KEY` |
| 4 | Wikimedia Commons | kategorie parku z podkategoriami + `Photographs taken on 2026-10-17` zawężone do Chorzowa, data z `DateTimeOriginal` | brak, ale ustaw `CONTACT_EMAIL` |
| 5 | Linki ręczne | Instagram, TikTok, X (`since/until` i `since_time/until_time`), Google Maps, Facebook, galerie lokalnych mediów | brak |
| 6 | Wydarzenia | ustalenia z researchu z poziomem pewności + wzmianki o dacie na publicznych stronach obiektów (z robots.txt) | brak |
| 7 | Kamery | Windy Webcams API w promieniu parku, info o timelapse/archiwum, plus katalogi kamer do ręcznego przejrzenia | `WINDY_WEBCAMS_API_KEY` (opcjonalnie) |

## Jak zdobyć klucze

Wszystkie są darmowe do użytku prywatnego. Najprościej przez kreator:

```bash
python -m parkosint keys
```

* **YouTube robi się sam.** Jeśli masz zainstalowane [Google Cloud CLI](https://cloud.google.com/sdk/docs/install),
  kreator otworzy logowanie Google (jedyny krok dla Ciebie), a potem sam założy projekt, włączy YouTube Data API,
  utworzy klucz ograniczony do tego API i wpisze go do `.env`. Przy zupełnie nowym koncie Google może poprosić,
  żebyś raz wszedł na console.cloud.google.com i zaakceptował regulamin.
* **Mapillary, Flickr, Windy** nie mają API do zakładania kluczy. Kreator otwiera właściwą stronę, mówi co kliknąć,
  Ty wklejasz klucz, a kreator go sprawdza i zapisuje. W pełni automatycznie się nie da bez podania programowi
  Twojego hasła i przeklikania za Ciebie logowania i regulaminu, a tego celowo nie robimy.

Ręcznie, krok po kroku:

**Flickr**

Uwaga: jedno źródło podaje, że nowe klucze wymagają teraz płatnego konta Pro, ale oficjalna strona Flickra
tego nie potwierdza. Jeśli formularz zażąda Pro, pomiń Flickra, to najmniej istotne źródło dla parku w Polsce.

1. Załóż konto na flickr.com i zaloguj się.
2. Wejdź na https://www.flickr.com/services/apps/create/apply/ i wybierz *Apply for a Non-Commercial Key*.
3. Podaj nazwę (np. "park-slaski-osint") i krótki opis. Dostajesz *Key* i *Secret*. Do `.env` wpisujesz tylko **Key**.

**Mapillary**
1. Zaloguj się na mapillary.com.
2. Wejdź na https://www.mapillary.com/dashboard/developers i kliknij *Register application*.
3. Nazwa, opis, strona (może być dowolna), callback URL np. `http://localhost`, uprawnienie *Read*.
4. Skopiuj **Client Token** (zaczyna się od `MLY|`) do `MAPILLARY_ACCESS_TOKEN`.

**YouTube Data API v3**
1. https://console.cloud.google.com/ i utwórz projekt.
2. *APIs & Services*, *Library*, wyszukaj **YouTube Data API v3**, kliknij *Enable*.
3. *Credentials*, *Create credentials*, *API key*. Najlepiej ogranicz klucz do YouTube Data API v3.
4. Darmowy limit to 10 000 jednostek dziennie. Jedno `search.list` kosztuje 100, więc domyślny przebieg
   (8 fraz po 2 strony) zużywa ok. 1 600 jednostek. Mniej: `--yt-pages 1`.

**Windy Webcams (opcjonalnie)**
1. https://api.windy.com/keys, zaloguj się, utwórz klucz dla *Webcams API*.
2. W darmowym planie część timelapse'ów może nie być dostępna, raport pokaże, co API zwróciło.

**Kolejność, jeśli nie chcesz zakładać wszystkiego:** YouTube (najwięcej materiału z wydarzeń),
potem Mapillary, potem Flickr. Commons działa od razu bez klucza.

**Uruchomienie w chmurze Claude Code zamiast na komputerze:** w ustawieniach środowiska (menu środowiska
w pasku tytułu sesji, potem Edit) dodaj zmienne `FLICKR_API_KEY`, `MAPILLARY_ACCESS_TOKEN`, `YOUTUBE_API_KEY`,
`WINDY_WEBCAMS_API_KEY`, `CONTACT_EMAIL` i dopuść w Network access hosty `api.flickr.com`, `graph.mapillary.com`,
`commons.wikimedia.org`, `upload.wikimedia.org`, `live.staticflickr.com`, `api.windy.com`. Nowa sesja je zobaczy.
Kluczy nie wklejaj do czatu.

**Wikimedia Commons** nie wymaga klucza. Wpisz tylko `CONTACT_EMAIL`, bo zasady Wikimedia wymagają
kontaktu w nagłówku User-Agent. Ten e-mail nie trafia nigdzie indziej.

## Polecenia

```bash
python -m parkosint run                                   # pełny przebieg, punkt 50.2795,18.9902
python -m parkosint run --point 50.2801,18.9915          # inny punkt jednorazowo
python -m parkosint run --sources commons,events          # tylko wybrane źródła
python -m parkosint run --margin 75                       # gdy podejrzewasz aparat bez zmiany czasu na letni
python -m parkosint run --commons-geo-scan                # dodatkowy (wolniejszy) skan Commons po geotagach
python -m parkosint links                                 # same linki do ręcznego sprawdzenia
python -m parkosint doctor                                # klucze i dostęp do API
python -m parkosint letters                               # wypełnia pisma z letters/dane.yaml
python -m pytest                                          # testy
```

Najważniejsze opcje `run`:

| Opcja | Domyślnie | Po co |
|---|---|---|
| `--point LAT,LON` | 50.2795,18.9902 | punkt, od którego liczona jest odległość. Kolejność: `--point`, potem `REFERENCE_POINT` z `.env`, potem domyślny |
| `--date / --start / --end` | 2026-10-17, 16:15, 18:00 | inne okno, gdyby było potrzebne |
| `--margin` | 30 | minuty zapasu w zapytaniach. Wyniki z marginesu mają żółtą etykietę |
| `--keep-out` | wyłączone | zostawia wyniki z dokładnym czasem spoza okna (np. ten sam dzień, inna godzina) |
| `--no-thumbs` | wyłączone | nie pobiera miniatur (część linków Mapillary szybko wygasa, więc lepiej pobierać) |
| `--interval` | 1.0 | min. odstęp między zapytaniami do jednego hosta w sekundach |

## Jak czytać raport

* **Czas** zawsze w czasie Warszawy. Etykieta mówi, skąd jest:
  *EXIF DateTimeOriginal* (najlepszy), *czas wykonania wg serwisu*, *czas z urządzenia* (Mapillary),
  *start transmisji na żywo*, *data nagrania od autora*, albo **czas publikacji, NIE wykonania** (YouTube bez metadanych).
* **Zielona etykieta „w oknie”** to 16:15 do 18:00. Żółta to margines.
* Aparaty zapisują czas bez strefy. Zakładamy czas polski. Jeśli aparat nie przestawił się na czas letni,
  zdjęcie pokaże godzinę mniej. 17.10.2026 obowiązywał jeszcze czas letni (zmiana dopiero 25.10).
* **Zachód słońca** 17.10 w Chorzowie był ok. 17:49, więc po 17:30 zdjęć będzie mniej i będą ciemne.
* **Odległość** liczona od Twojego punktu do geotagu zdjęcia (czyli miejsca, gdzie stał fotograf, nie tego, co jest na zdjęciu).
  Filtr „ukryj dalej niż” w raporcie pomaga odsiać resztę parku.
* YouTube: wynik musi mieć w tytule lub opisie nazwę miejsca. Punkty „trafności” rosną za datę w opisie,
  `recordingDate` = 17.10 albo transmisję live nachodzącą na okno.

## Zasady, których narzędzie pilnuje

* tylko oficjalne API i publiczne strony, bez logowania, bez omijania zabezpieczeń, bez scrapowania Instagrama, TikToka, X i Facebooka,
* robots.txt sprawdzany przy każdym pobraniu zwykłej strony WWW (wydarzenia), API wołane zgodnie z ich limitami,
  z odstępem min. 1 s na host i ponawianiem po 429/5xx z `Retry-After`,
* żadnego Tora, darkwebu ani rozpoznawania twarzy. Narzędzie w ogóle nie analizuje obrazu,
* pobierane są tylko miniatury do raportu, oryginały zostają u źródła,
* klucze tylko w `.env` (w `.gitignore`), w komunikatach błędów są maskowane.

Raport zawiera wizerunki innych osób i cudze zdjęcia. Używaj go do własnej sprawy, nie publikuj dalej.
Jeśli coś znajdziesz, zapisz link i zrób zrzut, a o oryginał poproś autora.

## Struktura

```
parkosint/
  __main__.py        CLI
  config.py          bbox parku, frazy, kategorie, ustawienia z .env
  http.py            limit zapytań, ponawianie, robots.txt, maskowanie kluczy
  timeutil.py        okno czasowe, strefy, parsowanie EXIF
  sources/           flickr, mapillary, youtube, commons, events, webcams
  links.py           linki do ręcznego sprawdzenia
  report.py          report.html + results.csv/json
  templates/         szablon raportu
  resources/         ustalenia o wydarzeniach z 17.10.2026
letters/             szablony pism + instrukcja
tests/               testy (odpowiedzi API w testach to przykłady w formacie z dokumentacji)
```

## Osobne repozytorium

Projekt leży w katalogu `park-slaski-osint/` repozytorium `bot-`. Żeby zrobić z niego osobne repo z historią:

```bash
git subtree split --prefix park-slaski-osint -b park-slaski-osint
# potem: utwórz puste repo na GitHubie i
git push git@github.com:<login>/park-slaski-osint.git park-slaski-osint:main
```
