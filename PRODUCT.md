# Product

<!-- impeccable:product-schema 1 -->

> Plik powstał bez wywiadu: właściciel poprosił, żeby nie zadawać pytań. Wszystko, co nie wynika
> wprost z kodu lub README, jest oznaczone jako **(założenie)** i czeka na potwierdzenie.

## Platform

web

## Users

- **Operator bota** (założenie: jedna osoba, właściciel repo, polskojęzyczna, uruchamia projekt lokalnie,
  według README głównie na Windowsie). Odpala `python dashboard.py`, trzyma panel otwarty w karcie
  przeglądarki i co jakiś czas sprawdza, czy bot żyje, w jakim jest trybie, czy ma pozycję i co
  robią wieloryby. Nie klika w panelu niczego, bo panel tylko pokazuje stan.
- **Ten sam operator jako odbiorca raportów typera** (`typer/`): raport dzienny i ocena modelu
  w HTML, na Telegramie i w CLI.

## Product Purpose

Dwa narzędzia w jednym repo, oba z tą samą zasadą: pokazać uczciwie, czy jest przewaga, i nie działać,
gdy jej nie ma.

1. **Bot spot (ccxt)** z backtestem walk-forward, bramkami jakości out-of-sample, monitoringiem dużych
   graczy z publicznych danych i panelem na żywo (`dashboard.py` + `static/dashboard.html`).
   Domyślnie paper trading (`DRY_RUN=true`). Jeśli żadna strategia nie przejdzie bramek,
   `STRATEGY=OPTIMIZED` nie handluje.
2. **Typer piłkarski** (`typer/`): skalibrowane prawdopodobieństwa 1X2, O/U 2.5, BTTS, bramki jakości,
   na razie tylko typowanie i paper.

Sukces panelu: operator w kilka sekund wie, czy bot działa, czy handluje na prawdziwe pieniądze,
czy ma otwartą pozycję i jak ona stoi.

## Positioning

Brak obietnic zysku. Projekt mierzy wynik wyłącznie poza próbą i sam blokuje handel bez przewagi.
Każda liczba pochodzi z pliku albo obliczenia, niczego się nie wpisuje ręcznie.

## Operating Context

- Panel działa na `http://127.0.0.1:5000`, bot chodzi w wątku w tle. Stan odświeża się co 5 s
  (`/api/state`), świece co 30 s (`/api/candles`), zdrowie bota pod `/api/health`.
- Tryby: **PAPER** (domyślny) i **LIVE** (prawdziwe zlecenia). Pomylenie ich to najdroższy możliwy błąd.
- Wieloryby: wynik −1…+1 z taśmy transakcji, orderbooku, top traderów Binance Futures i Hyperliquid.
  To heurystyka, której nie da się zbacktestować.
- Panel jest otwierany obok innych narzędzi, często zerknięciem (założenie).

## Capabilities and Constraints

- Panel: wykres świecowy (lightweight-charts 4.2.0 z CDN unpkg), linie Entry/SL/TP, znaczniki
  sygnałów i transakcji, statusy w nagłówku (para, strategia, tryb, pozycja), panele: status,
  wieloryby, statystyki, ostatnie sygnały, historia transakcji.
- Panel jest tylko do odczytu. Nie ma przycisków sterujących botem.
- Bez kroku budowania: jeden statyczny plik HTML z CSS i JS w środku, serwowany przez Flask.
- Język interfejsu: polski, liczby w formacie `pl-PL`. Kwoty w USDT.
- Raporty typera: HTML generowany w Pythonie (`typer/typer/report/render.py`) i testowany
  (kontrast tokenów ≥ 4,5:1, statusy zawsze podpisane słowem).
- Nieustalone: czy panel ma działać na telefonie (założenie: głównie desktop) i czy ma działać bez
  dostępu do CDN.

## Brand Commitments

- Nazwa robocza: „Trading Bot”. Ton z README: rzeczowy, bez obietnic, z sekcjami „Uczciwie”.
- Brak logo i formalnej identyfikacji.

## Evidence on Hand

- Brak prawdziwych wyników handlu w repo (`trade_log.json` i `best_params.json` są w `.gitignore`).
  Żaden ekran ani dokument nie może pokazywać zmyślonych zwrotów, win rate ani zrzutów z zyskiem.
- Raporty walidacyjne typera: `typer/backtest/**.json`, `typer/reports/`.

## Product Principles

1. **Bezpieczeństwo trybu ponad wszystko.** LIVE ma być nie do przeoczenia, PAPER spokojny.
2. **Uczciwość liczb.** Brak danych to „brak danych”, nie zero i nie myślnik udający wartość.
   Heurystyki są podpisane jako heurystyki.
3. **Status czytelny bez koloru.** Kolor wspiera, słowo i znak (+/−) niosą znaczenie.
4. **Zerknięcie wystarczy.** Najważniejsze odpowiedzi (żyje? tryb? pozycja? wynik?) widać bez przewijania.
5. **Bez obietnic.** Interfejs nie sugeruje zysku, którego nie zmierzono poza próbą.

## Accessibility & Inclusion

Brak ustalonego standardu dla panelu (założenie: WCAG 2.1 AA jako rozsądne minimum).
W typerze obowiązuje już kontrast ≥ 4,5:1 i status podpisany słowem; panel powinien trzymać ten sam poziom.
