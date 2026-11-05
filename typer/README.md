# Typer piłkarski

Program typujący mecze piłkarskie (1X2, over/under 2.5, BTTS; handicapy azjatyckie liczone z tej samej
macierzy wyników), który uczy się po każdym rozliczonym meczu, sam pokazuje, gdzie się myli, i przechodzi
automatyczne bramki jakości (`tools/evaluate.py`), zanim zostanie uznany za gotowy.
Zbudowany według skilla *typer-sportowy*.

> **Uczciwie:** to narzędzie wspiera decyzje, nie gwarantuje zysku. „Pewniaków na 100%” nie ma.
> Model mierzy prawdopodobieństwa i to, czy są lepsze od kursu. Gra tylko u legalnych bukmacherów
> i kwotami, których utrata nie boli. W Polsce legalni bukmacherzy pobierają 12% podatku od stawki
> (`tax_rate: 0.12` w `config/model.yaml`), co mocno podnosi próg opłacalności.

## 1. Jak mierzymy sukces (ustalone przed pisaniem kodu)

* **Trafność w procentach nic nie znaczy.** Typowanie samych faworytów daje dużo trafień i stratę.
* **Cel 1: skalibrowane prawdopodobieństwa.** Log loss, Brier, ECE (bramka: ECE ≤ 0,03).
* **Cel 2: przewaga nad rynkiem, mierzona CLV** względem kursu zamknięcia **bez marży**.
  ROI to głównie szum, więc raportujemy go zawsze z przedziałem ufności.
* Model, który „bije zamknięcie” o dużo, prawie na pewno ma wyciek danych (bramka `brak_wycieku`).
* Każda liczba w raportach pochodzi z pliku albo obliczenia. Niczego nie wymyślamy.

## 2. Ustalenia startowe (przyjęte domyślne, bo nikt ich nie zmienił)

| Pytanie | Przyjęte |
|---|---|
| Sport i ligi | Piłka nożna: Premier League, Bundesliga, Serie A, La Liga, Ligue 1, Ekstraklasa |
| Rynki | 1X2, O/U 2.5, BTTS (+ AH i inne linie O/U z tej samej macierzy) |
| Źródła i budżet | Darmowe: football-data.co.uk (przez kopię na GitHubie, patrz niżej), The Odds API (darmowy plan) |
| Wysyłka typów i raportów | JSON na webhook n8n (`N8N_WEBHOOK_URL`), który formatuje wiadomość na Telegram |
| Baza | PostgreSQL w produkcji (`DATABASE_URL`), SQLite domyślnie (prototyp i testy) |
| Pieniądze | **Na razie tylko typowanie i paper trading** (`bets.paper = true`) |

Zmiana ustaleń: `config/sports.yaml`, `config/sources.yaml`, `config/gates.yaml`, `config/model.yaml`.

## 3. Dane i ich ograniczenia (ważne)

W sesji, w której powstał projekt, polityka sieci blokowała `www.football-data.co.uk`,
`api.the-odds-api.com`, API-Sports, Understat, FBref i Club Elo. Dostępne były tylko PyPI i GitHub.
Dlatego historia pochodzi z **[xgabora/Club-Football-Match-Data](https://github.com/xgabora/Club-Football-Match-Data-2000-2025)**
(licencja MIT; dane źródłowe: [football-data.co.uk](https://www.football-data.co.uk/) i [ClubElo](http://clubelo.com/)),
przypiętej do commita `25882a5` (mecze do 2026-09-03).

Co z tego wynika:

1. **Brak kursów zamknięcia.** Kopia ma kursy Bet365 i maksymalne **sprzed meczu** (football-data zbiera je
   w piątek dla meczów weekendowych i we wtorek dla środowych), ale nie ma zamknięć Pinnacle.
   Bez zamknięcia nie da się policzyć CLV, więc bramka `clv_dodatni` nie może przejść, a najlepszy możliwy
   werdykt to „gotowy tylko do typowania”. To jest uczciwe ograniczenie danych, nie błąd modelu.
2. **Ekstraklasa:** dane kończą się 2024-10-06, nie ma strzałów ani kursów O/U, a moment zebrania kursów 1X2
   jest nieznany, więc używamy ich wyłącznie jako benchmarku rynku, nigdy jako kursu „wziętego”.
   W kopii wykryliśmy i naprawiliśmy zamienione dni z miesiącami (`experiments.md`, wpis 0).
3. **Brak składów i kontuzji.** To największa „ślepa plamka” (oficjalne składy ~60 min przed meczem to
   największa pojedyncza aktualizacja informacji). Adapter API-Football (`typer/ingest/api_football.py`) zbiera je
   do tabeli `lineups`, gdy podasz `API_FOOTBALL_KEY` i host będzie dostępny. Model jeszcze ich nie używa,
   bo nie ma historii do walidacji.

**Żeby odblokować pełną wersję:** w ustawieniach środowiska (Network access) dodaj do dozwolonych hostów
`www.football-data.co.uk` (wyniki + zamknięcia Pinnacle + `fixtures.csv`) i `api.the-odds-api.com`
(snapshoty kursów na żywo; klucz w `.env`). Adapter `typer/ingest/footballdata_uk.py` mapuje
`PSCH/PSCD/PSCA` i `PC>2.5/PC<2.5` na `close_*`, a backtest wpisze je do `odds_close`.

Źródła z licencjami i limitami: `config/sources.yaml`. Flashscore: tylko ręczna weryfikacja, bez scrapowania
(regulamin zabrania pobierania treści bez zgody).

## 4. Architektura

```
typer/
  config/            sports.yaml, sources.yaml, gates.yaml, model.yaml (wynik strojenia)
  typer/
    ingest/          xgabora (GitHub), footballdata_uk (docelowe), odds_api, api_football (składy);
                     schema = kontrakt danych, budget = limity zapytań API
    store/           SQLAlchemy: 12 tabel minimum, predictions i bets tylko do dopisywania (triggery), alembic
    entities/        mapowanie nazw drużyn: alias -> dopasowanie rozmyte -> kolejka do ręcznej weryfikacji;
                     history = spójność nazw w historii (zmiany zapisu w trakcie sezonu)
    features/        reguły "as of" (odcięcie piątek/wtorek jak zbieranie kursów), forma drużyn
    models/          baseline (częstości), ratings/elo, scores/online_poisson (rdzeń), scores/dixon_coles
                     (challenger, penaltyblog), scores/matrix (Poisson + korekta DC, normalizacja do 1),
                     calibration/
    markets/         macierz wyników -> 1X2, O/U (dowolna linia), BTTS, AH (także ćwiartkowe)
    betting/         de-vig, przewaga, ułamkowy Kelly, limity (2%/zakład, 10%/dzień, 1 zakład/mecz, stop -25%)
    learn/           settle (rozliczenie jako widok), journal (dziennik błędów), champion (bootstrap sparowany)
    pipeline/        engine (walk forward), tune, layers (kalibracja, LightGBM, mieszanka z rynkiem), backtest, daily
    report/          fmt (tokeny i formaty), render (komponenty, CLI/Telegram/HTML), daily (JSON raportu,
                     dzienny i tygodniowy, webhook n8n), analysis (kontrole danych, korekta Bonferroniego)
  tools/evaluate.py  bramki jakości (Załącznik A skilla, bez zmian)
  tests/             pytest (sekcja 12 skilla)
  experiments.md     dziennik eksperymentów
  cli.py             fetch | snapshot | lineups | predict | settle | learn | report | analyze | budget |
                     backtest | tune | journal | day
  sql/analiza.sql    szablony zapytań PostgreSQL (sekcja 14.4)
  scripts/           crontab.txt (Europe/Warsaw), run.sh (log + alarm przy błędzie)
```

### Model

1. **Benchmarki:** rynek (kurs bez marży) i baseline = częstości wyników w lidze (kolumna `p_baseline`).
2. **Oceny online** (`models/scores/online_poisson.py`): siła ataku i obrony każdej drużyny, przewaga gospodarza
   i poziom goli **per liga**, aktualizowane po każdym meczu krokiem gradientu wiarygodności Poissona.
   Cel aktualizacji łączy gole z proxy xG ze strzałów (celne i niecelne). Beniaminkowie startują z niższej
   oceny i uczą się szybciej, między sezonami oceny wracają częściowo do średniej.
3. **Rozkład wyniku:** Poisson z korektą Dixona-Colesa niskich wyników, macierz 0..10 goli normalizowana do 1.
   Wszystkie rynki liczone z jednej macierzy, więc są spójne.
4. **Warstwy (kroczące, sezon po sezonie):** kalibracja, LightGBM, mieszanka z rynkiem. Wybór warstw
   na walidacji, wynik w `experiments.md`.

## 5. Wyniki i werdykt (walidacja 2018/19 do 2024/25, holdout 2025/26 + start 2026/27)

Szczegóły i wszystkie odrzucone pomysły: `experiments.md`. Pełne raporty `evaluate.py`: `backtest/report_*.txt`.

**Werdykt (walidacja i holdout): GOTOWY tylko do typowania (brak dowodu przewagi nad rynkiem).**

| Log loss, holdout (1851 meczów) | Champion | Same oceny online | Rynek* | Baseline |
|---|---|---|---|---|
| 1X2 | **0,9758** | 0,9895 | 0,9763 | 1,0707 |
| O/U 2.5 | **0,6753** | 0,6842 | 0,6753 | n/d |
| BTTS | **0,6860** | 0,6871 | brak kursów | n/d |

\* Bet365 sprzed meczu bez marży (kursów zamknięcia w danych nie ma).

Co to znaczy po ludzku:

1. **Prawdopodobieństwa są dobre:** ECE 0,004 na holdoucie, model bije baseline o 0,036 log loss,
   żadnej bramki twardej nie oblewa, bramka `brak_wycieku` przechodzi (luka do rynku −0,0002).
2. **Ale sam model nie wie więcej niż bukmacher.** Same oceny online są słabsze od kursu Bet365 o ~0,013
   w 1X2. Mieszanka z rynkiem, dopasowywana krocząco, dała modelowi wagę **0,0** w każdym sezonie walidacji.
   Wniosek: z goli i strzałów nie da się w top 5 lig wycisnąć informacji, której nie ma już w kursie.
   Champion to w praktyce skalibrowany rynek (dla lig bez kursów: skalibrowany model).
3. **Gra pieniędzmi: nie.** Surowy model typujący „value bety” przy progu 5% miał na walidacji ROI −9,7%
   (CI90 −12,2% do −7,2%, 13 858 zakładów): jego „przewagi” to jego własne błędy. Champion znajduje
   przewagę ≥ 5% prawie nigdy (10 zakładów w 7 sezonach, 0 na holdoucie), więc sam z siebie nie gra.
   Dowodu przewagi (CLV) nie ma i bez kursów zamknięcia być nie może.
4. **Ekstraklasa:** jedyny segment z flagą „słaby” (luka +0,016 do benchmarku). Dane kończą się w 2024, nie ma
   strzałów, a moment kursów jest nieznany. Typy dla Ekstraklasy traktuj ostrożnie.
5. **Premier League (tryb NAPRAWA, skill v2):** alarm dryfu E0/1X2 z holdoutu znika przy nowych progach
   detektora (k = 0,2, h = 20), a flaga „słaby” (luka +0,0024) nie przechodzi korekty Bonferroniego na
   10 segmentów (p = 0,043 przy progu 0,005). Najpewniej przypadek. Hipoteza o kalibracji typuje jako
   challenger `op-v1-nocal` w cieniu. Przy okazji diagnozy znalazły się i zostały naprawione trzy zmiany zapisu
   nazw w źródle w trakcie sezonu (Forest, Gladbach, Górnik): `experiments.md`, wpisy 11 do 14.

**Ponowna ocena narzędziem v2** (te same zamrożone predykcje, bez przeliczania): werdykt bez zmian; nowa bramka
„baseline w każdym rynku” przechodzi (holdout: 1X2 −0,0949, O/U −0,0107, BTTS −0,0021); jeden zakład na mecz OK.
Raporty v2: `backtest/v2/`.

**Co dalej, w kolejności wpływu:** (1) odblokować `www.football-data.co.uk` i `api.the-odds-api.com`, żeby mieć
kursy zamknięcia i snapshoty na żywo (CLV); (2) klucz API-Football i dostęp do `v3.football.api-sports.io`
(adapter już jest), żeby zacząć zbierać składy, bo to największa brakująca informacja; (3) prawdziwe xG; (4) dopiero potem paper trading przez min.
4 tygodnie / 300 zakładów i ponowne bramki. Gdy przewagi nadal nie będzie, uczciwa odpowiedź brzmi:
typer daje dobre prawdopodobieństwa, ale nie daje powodu, żeby grać.

## 6. Uruchomienie

```bash
cd typer
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # klucze tylko tutaj
.venv/bin/python -m pytest -q -m "not slow"   # szybkie testy (< 1 min, przy każdym commicie)
.venv/bin/python -m pytest -q                  # wszystkie, z testami statystycznymi i regresją (nocą)
.venv/bin/alembic upgrade head  # schemat bazy (albo automatycznie przy pierwszym poleceniu)

.venv/bin/python cli.py backtest                 # walidacja: plik predykcji + evaluate.py + werdykt
.venv/bin/python cli.py backtest --compare online,online+cal,online+cal+blend
.venv/bin/python cli.py backtest --holdout       # RAZ, na końcu (zostaje znacznik backtest/HOLDOUT_USED)
.venv/bin/python cli.py tune                     # strojenie ocen online na walidacji

# cykl dzienny (na żywo, po odblokowaniu źródeł)
.venv/bin/python cli.py fetch && .venv/bin/python cli.py snapshot   # snapshot pilnuje budżetu kredytów
.venv/bin/python cli.py lineups                  # składy i kontuzje (API-Football), na razie tylko zbieranie
.venv/bin/python cli.py predict --lead-minutes 90   # champion + challenger w cieniu; zakłady tylko champion
.venv/bin/python cli.py settle && .venv/bin/python cli.py report --send --html live/dzis.html
.venv/bin/python cli.py learn                    # evaluate.py od daty wdrożenia + challenger vs champion
.venv/bin/python cli.py report --weekly          # przegląd tygodniowy: bramki, segmenty po korekcie, kontrole
.venv/bin/python cli.py budget                   # zużycie limitów API i szacunek kredytów z historii

# analiza wyników (sekcja 14) i render dowolnego raportu evaluate.py (np. backtestu) do CLI + HTML
.venv/bin/python cli.py analyze --league POL --market 1X2 --since 2025-08-01
.venv/bin/python cli.py analyze --csv backtest/preds_market_valid.csv --league POL,E0 --market 1X2
.venv/bin/python cli.py report --from-json backtest/v2/report_market_holdout.json \
    --csv backtest/preds_market_holdout.csv --html live/holdout.html

# tryb odtworzeniowy: cała pętla na prawdziwym dniu z historii (np. gdy źródła na żywo są niedostępne)
.venv/bin/python cli.py day --as-of 2026-08-30
```

Harmonogram: `scripts/crontab.txt` (07:00 pobranie, co 15 min snapshoty i typy 60 do 90 min przed meczem,
02:00 rozliczenie i raport, poniedziałek 06:00 przegląd tygodniowy, 1. dnia miesiąca challenger).

### Budżet zapytań (sekcja 5 v2)

| Źródło | Limit (plan darmowy, wg skilla, listopad 2026) | Jak go pilnujemy |
|---|---|---|
| The Odds API | 500 kredytów/mies., koszt = rynki × regiony | snapshot typu raz na ligę i dzień meczowy, zamknięcie na każdą godzinę startu; zamknięcia mają priorytet, przy braku budżetu „typ” traci totals, potem odpada. Na danych 2025/26 dla 5 lig: średnio 380, maks. 498 kredytów/mies. |
| API-Football | 100 zapytań/dzień, reset o północy UTC | terminarz i kontuzje raz na ligę i dzień, skład raz na mecz |

Zużycie liczymy z nagłówków API (`x-requests-used`, `x-ratelimit-requests-remaining`) w `live/budget.json`;
zapytanie ponad budżet (z 10% rezerwy) nie wychodzi, tylko trafia jako alarm do raportu.

### Spójność nazw (sekcja 4)

Nazwy różniące się tylko interpunkcją łączymy automatycznie (z logiem). Każda inna zmiana nazwy w trakcie sezonu
(jedna nazwa znika, druga pojawia się zaraz po) **blokuje pobranie** z komunikatem, dopóki człowiek nie wpisze
decyzji do `config/aliases.yaml`. Nic po cichu.

### Raporty (sekcja 13)

Jeden JSON (`schema: typer.report/v2`) i trzy widoki z tymi samymi tokenami: CLI (`[OK]`, `[UWAGA]`, `[BLAD]`,
`[--]`, szerokość ≤ 100), Telegram (✅ ⚠️ ⛔ ➖, wiadomości ≤ 4096 znaków, najpierw werdykt i typy, każdy alarm
osobno) i HTML (kontrast ≥ 4,5:1, status zawsze podpisany słowem, `<th scope>`, cyfry stałej szerokości).
Formaty liczb są w jednym miejscu: `typer/report/fmt.py`. Metryka z n < 100 dostaje `[--]` i dopisek
„za mało danych”, ROI zawsze z przedziałem.

### Testy (sekcja 12)

* `tests/test_evaluate.py` i `tests/synth.py`: Załączniki D i C skilla bez zmian (18 testów narzędzia).
* Właściwości (`hypothesis`): macierz, O/U, AH 0 = DNB, de-vig, Kelly, limity, Elo; `betting/` i `markets/`
  mają 100% pokrycia gałęzi.
* Złoty plik aliasów, kontrakty adapterów (pole zniknęło = test czerwony), podróż w czasie na wszystkich cechach,
  modele z wyciekiem dla każdej klasy (oceny online, LightGBM), void i zwroty w rozliczeniu, challenger bez
  awansu poniżej 300 zdarzeń, snapshot raportu, strażnik penaltyblog/scipy, regresja log loss i ECE.
* CI: `.github/workflows/typer.yml` (szybkie testy przy pushu i PR, pełne nocą; kod 3 z `evaluate.py` blokuje).

### Nauka dzień po dniu

* Oceny online: po każdym meczu. Kalibracja i warstwy: dopasowywane na całej historii przy każdym typowaniu.
* Dziennik błędów: typ, w którym model dał faktycznemu wynikowi < 10%, trafia do `error_journal` z podpowiedzią
  (`SZUM?` przy czerwonej kartce). Człowiek ustala klasę: `python cli.py journal --classify ID SLEPA_PLAMKA --note "brak składu"`.
  Cechę dodajemy dopiero, gdy ta sama ślepa plamka wraca kilka razy i poprawia walidację.
* Dryf: CUSUM w `evaluate.py` z `--since` = data wdrożenia bieżącej wersji (z `model_registry`).
* Champion/challenger: challengerzy z `config/model.yaml` typują w cieniu przy każdym `predict`
  (`role = challenger`, bez zakładów), awans tylko gdy CI90 różnicy log loss w sparowanym bootstrapie < 0
  na ≥ 300 zdarzeniach i bramki są zaliczone (`learn/champion.py`).
* Dryf: progi detektora w `config/gates.yaml` (`drift.k`, `drift.h`); po kilku tygodniach na żywo policz fałszywe
  alarmy i w razie potrzeby podnieś `h`.

### Webhook n8n

`python cli.py report --send` wysyła POST z JSON-em na `N8N_WEBHOOK_URL`: dane raportu (`schema`, `typy`,
`wczoraj`, `okna`, `segmenty`, `alarmy`, `wnioski`) plus gotowe widoki: `telegram` (lista wiadomości ≤ 4096 znaków),
`html` (załącznik) i `tekst` (CLI). n8n niczego nie liczy: Webhook → Split Out (`telegram`) → Telegram Send Message.
Lokalnie zawsze zapisuje się `live/report_<data>.json`, `.txt` i `.html`.

## 7. Atrybucja

* Dane: [football-data.co.uk](https://www.football-data.co.uk/), [ClubElo](http://clubelo.com/), kopia
  [xgabora/Club-Football-Match-Data-2000-2025](https://github.com/xgabora/Club-Football-Match-Data-2000-2025) (MIT).
* Dixon-Coles: [penaltyblog](https://github.com/martineastwood/penaltyblog) (MIT), Martin Eastwood.
