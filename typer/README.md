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
   największa pojedyncza aktualizacja informacji). Tabela `lineups` jest gotowa, źródła brak.

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
    ingest/          xgabora (GitHub), footballdata_uk (docelowe), odds_api; schema = kontrakt danych
    store/           SQLAlchemy: 12 tabel minimum, predictions i bets tylko do dopisywania (triggery), alembic
    entities/        mapowanie nazw drużyn: alias -> dopasowanie rozmyte -> kolejka do ręcznej weryfikacji
    features/        reguły "as of" (odcięcie piątek/wtorek jak zbieranie kursów), forma drużyn
    models/          baseline (częstości), ratings/elo, scores/online_poisson (rdzeń), scores/dixon_coles
                     (challenger, penaltyblog), scores/matrix (Poisson + korekta DC, normalizacja do 1),
                     calibration/
    markets/         macierz wyników -> 1X2, O/U (dowolna linia), BTTS, AH (także ćwiartkowe)
    betting/         de-vig, przewaga, ułamkowy Kelly, limity (2%/zakład, 10%/dzień, 1 zakład/mecz, stop -25%)
    learn/           settle (rozliczenie jako widok), journal (dziennik błędów), champion (bootstrap sparowany)
    pipeline/        engine (walk forward), tune, layers (kalibracja, LightGBM, mieszanka z rynkiem), backtest, daily
    report/          raport dzienny + webhook n8n
  tools/evaluate.py  bramki jakości (Załącznik A skilla, bez zmian)
  tests/             pytest (sekcja 12 skilla)
  experiments.md     dziennik eksperymentów
  cli.py             fetch | snapshot | predict | settle | learn | report | backtest | tune | journal | day
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
5. **Do obserwacji:** na holdoucie Premier League 1X2 ma minimalną, ale istotną lukę do rynku i alarm dryfu
   od lutego 2026. Holdout jest spalony, więc to idzie do monitoringu, nie do strojenia.

**Co dalej, w kolejności wpływu:** (1) odblokować `www.football-data.co.uk` i `api.the-odds-api.com`, żeby mieć
kursy zamknięcia i snapshoty na żywo (CLV); (2) źródło składów i kontuzji (np. API-Football z kluczem),
bo to największa brakująca informacja; (3) prawdziwe xG; (4) dopiero potem paper trading przez min.
4 tygodnie / 300 zakładów i ponowne bramki. Gdy przewagi nadal nie będzie, uczciwa odpowiedź brzmi:
typer daje dobre prawdopodobieństwa, ale nie daje powodu, żeby grać.

## 6. Uruchomienie

```bash
cd typer
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # klucze tylko tutaj
.venv/bin/python -m pytest -q   # testy z sekcji 12
.venv/bin/alembic upgrade head  # schemat bazy (albo automatycznie przy pierwszym poleceniu)

.venv/bin/python cli.py backtest                 # walidacja: plik predykcji + evaluate.py + werdykt
.venv/bin/python cli.py backtest --compare online,online+cal,online+cal+blend
.venv/bin/python cli.py backtest --holdout       # RAZ, na końcu (zostaje znacznik backtest/HOLDOUT_USED)
.venv/bin/python cli.py tune                     # strojenie ocen online na walidacji

# cykl dzienny (na żywo, po odblokowaniu źródeł)
.venv/bin/python cli.py fetch && .venv/bin/python cli.py snapshot
.venv/bin/python cli.py predict --lead-minutes 90
.venv/bin/python cli.py settle && .venv/bin/python cli.py report --send
.venv/bin/python cli.py learn                    # przegląd tygodniowy od daty wdrożenia championa

# tryb odtworzeniowy: cała pętla na prawdziwym dniu z historii (np. gdy źródła na żywo są niedostępne)
.venv/bin/python cli.py day --as-of 2026-08-30
```

Harmonogram: `scripts/crontab.txt` (07:00 pobranie, co 15 min snapshoty i typy 60 do 90 min przed meczem,
02:00 rozliczenie i raport, poniedziałek 06:00 przegląd tygodniowy, 1. dnia miesiąca challenger).

### Nauka dzień po dniu

* Oceny online: po każdym meczu. Kalibracja i warstwy: dopasowywane na całej historii przy każdym typowaniu.
* Dziennik błędów: typ, w którym model dał faktycznemu wynikowi < 10%, trafia do `error_journal` z podpowiedzią
  (`SZUM?` przy czerwonej kartce). Człowiek ustala klasę: `python cli.py journal --classify ID SLEPA_PLAMKA --note "brak składu"`.
  Cechę dodajemy dopiero, gdy ta sama ślepa plamka wraca kilka razy i poprawia walidację.
* Dryf: CUSUM w `evaluate.py` z `--since` = data wdrożenia bieżącej wersji (z `model_registry`).
* Champion/challenger: nowa wersja typuje w cieniu (`role = challenger`), awans tylko gdy CI90 różnicy log loss
  w sparowanym bootstrapie < 0 na ≥ 300 zdarzeniach i bramki są zaliczone (`learn/champion.py`).

### Webhook n8n

`python cli.py report --send` wysyła POST z JSON-em na `N8N_WEBHOOK_URL`: pola `data`, `typy` (lista zakładów:
godz, liga, mecz, rynek, selekcja, p, kurs_fair, kurs, przewaga, stawka), `wczoraj`, `okna` (30/90 dni z evaluate.py),
`alarmy`, `wnioski` i `tekst` (gotowy raport). W n8n wystarczy Webhook → Telegram (Send Message, tekst `{{$json.body.tekst}}`).
Bez webhooka raport ląduje w `live/report_<data>.json`.

## 7. Atrybucja

* Dane: [football-data.co.uk](https://www.football-data.co.uk/), [ClubElo](http://clubelo.com/), kopia
  [xgabora/Club-Football-Match-Data-2000-2025](https://github.com/xgabora/Club-Football-Match-Data-2000-2025) (MIT).
* Dixon-Coles: [penaltyblog](https://github.com/martineastwood/penaltyblog) (MIT), Martin Eastwood.
