# Trading Bot

> W katalogu [`typer/`](typer/README.md) jest osobny projekt: **typer piłkarski** (oceny online, bramki jakości, cykl dzienny).

Bot spot (ccxt) z backtestem walk-forward, monitoringiem dużych graczy ("wielorybów")
i dashboardem na żywo. Domyślnie **paper trading** (`DRY_RUN=true`).

> **Uczciwie:** żadna strategia nie gwarantuje zysku. Ten projekt nie obiecuje rentowności –
> daje narzędzia, które pokazują, czy dane ustawienia miały przewagę **poza próbą**
> (na danych, których nie widziały przy doborze), i **nie pozwalają botowi handlować, jeśli jej nie mają**.

## Szybki start (Windows)

```powershell
pip install -r requirements.txt
copy .env.example .env
python optimize.py --symbol BTC/USDT --timeframe 1h --days 1095   # ~minuty, pobiera dane z giełdy
python dashboard.py                                               # http://localhost:5000
```

## 1. Dobór wskaźników i ustawień: `optimize.py`

* Strategie (`signals.py`): `ema_trend` (EMA cross + filtr EMA200), `rsi_revert` (RSI w trendzie), `donchian` (wybicie kanału).
* Każda ma siatkę parametrów + stop/target oparty o ATR.
* **Walk-forward**: parametry wybierane na 365 dniach, oceniane na kolejnych 90 niewidzianych dniach, okno się przesuwa.
  Raportowany jest tylko zszyty wynik **out-of-sample** (OOS) i porównanie z buy&hold.
* Model kosztów: prowizja 0,1%/stronę, poślizg 0,02%, wejście na otwarciu następnej świecy, przy wspólnym
  dotknięciu stopu i targetu wygrywa stop, luka przez stop = fill po cenie otwarcia.
* Sizing: strata przy stopie = 2% kapitału (`--risk`), pozycja ≤ `--max-alloc` kapitału.
* **Bramki jakości** (OOS): zwrot > 0, profit factor ≥ 1,2, ≥ 20 transakcji, max drawdown ≤ 30%, ≥ 50% foldów na plusie.
  Jeśli żadna strategia nie przejdzie, `best_params.json` mówi „brak” i `STRATEGY=OPTIMIZED` **nie handluje**.

Wyniki zależą od okresu i pary – uruchom dla swoich par/interwałów (`--symbol ETH/USDT --timeframe 4h`).
Przeszłość nie gwarantuje przyszłości; wynik OOS to nadal tylko próba historyczna.

`python optimize.py --synthetic` testuje kod na losowych danych (nic nie zapisuje).

## 2. Wieloryby: `whales.py`

Tylko **publiczne** dane (nie widać pojedynczych kont Binance):

| Źródło | Co daje |
|---|---|
| Taśma transakcji giełdy | alerty dla pojedynczych transakcji ≥ `WHALE_MIN_USD`, przepływ netto dużych zleceń z ostatniej godziny |
| Orderbook | nierównowaga głębokości ±1%, duże ściany (mogą być spoofingiem – mała waga) |
| Binance Futures | przesunięcie pozycji "top traderów" (long/short) względem ich historii |
| Hyperliquid | pozycje największych kont z leaderboardu + Twoje `WHALE_ADDRESSES`: otwarcie/zwiększenie/zamknięcie/odwrócenie ≥ `WHALE_MIN_USD` |

Wynik łączny −1…+1 (heurystyka, **nie da się jej cofnąć w czasie ani zbacktestować**).
`WHALE_MODE=filter` blokuje wejścia BUY, gdy wynik ≤ `−WHALE_BLOCK_SCORE`; `alert` tylko loguje.
Zdarzenia widać w panelu dashboardu. Szukanie "pozycji za miliony" na zewnętrznych portfelach
(np. on-chain przez Whale Alert/Arkham) wymaga płatnych kluczy API – nie jest wbudowane.

## 3. Bot

* Strategia reaguje **raz na zamkniętą świecę** (tak jak w backteście, brak repaintingu); stopy/targety sprawdzane co `POLL_SECONDS`.
* Stop w trybie LIVE jest sprawdzany co kilkadziesiąt sekund po stronie bota (nie jako zlecenie na giełdzie) – przy gwałtownym ruchu fill może być gorszy niż w backteście.
* `python main.py` – konsola, `python dashboard.py` – wykres (lightweight-charts) + panel wielorybów.

## Testy

```bash
pip install pytest && python -m pytest -q tests
```

## Architektura

```
signals.py     wspólna logika sygnałów (backtest = live)
backtest.py    silnik backtestu     optimize.py  walk-forward + bramki
data.py        pobieranie historii  whales.py    monitoring dużych graczy
strategy.py    strategie + OPTIMIZED  risk_manager.py  sizing/stopy
bot.py         pętla bota           exchange.py  wrapper ccxt
dashboard.py + static/dashboard.html   trade_log.py   config.py   logger.py
```

**Ostrzeżenie:** handel wiąże się z ryzykiem utraty środków. Zaczynaj od `DRY_RUN=true`.
