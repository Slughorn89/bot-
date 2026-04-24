# Trading Bot

Automatyczny bot handlowy oparty na analizie technicznej, obsługujący wiele giełd kryptowalut poprzez bibliotekę `ccxt`.

## Funkcje

- **3 strategie handlowe**: MA Crossover, RSI, MACD
- **Zarządzanie ryzykiem**: Stop Loss, Take Profit, limity pozycji
- **Tryb DRY RUN**: Paper trading bez ryzyka utraty środków
- **Obsługa wielu giełd**: Binance, Kraken, Coinbase i inne (przez ccxt)
- **Kolorowe logi**: Czytelny output w konsoli + zapis do pliku

## Instalacja

```bash
pip install -r requirements.txt
cp .env.example .env
# Uzupełnij .env swoimi danymi API
```

## Konfiguracja

Edytuj plik `.env`:

| Zmienna | Opis | Domyślnie |
|---------|------|-----------|
| `EXCHANGE` | ID giełdy (ccxt) | `binance` |
| `API_KEY` | Klucz API | – |
| `API_SECRET` | Secret API | – |
| `TRADING_PAIR` | Para handlowa | `BTC/USDT` |
| `TIMEFRAME` | Interwał świec | `1h` |
| `DRY_RUN` | Tryb paper trading | `true` |
| `STRATEGY` | Strategia | `MA_CROSSOVER` |
| `MAX_POSITION_SIZE` | Max % salda na trade | `0.1` |
| `STOP_LOSS_PCT` | Stop loss % | `0.02` |
| `TAKE_PROFIT_PCT` | Take profit % | `0.04` |
| `MAX_OPEN_TRADES` | Max otwartych pozycji | `3` |

## Uruchomienie

```bash
# Tryb paper trading (domyślny)
python main.py

# Wybór strategii przez CLI
python main.py --strategy RSI --pair ETH/USDT --timeframe 15m

# Tryb LIVE (uwaga: prawdziwe środki!)
python main.py --live
```

## Strategie

### MA_CROSSOVER (Golden/Death Cross)
Kupuje gdy szybka EMA(20) przebija wolną EMA(50) od dołu (Golden Cross).
Sprzedaje przy Death Cross.

### RSI
Kupuje gdy RSI wychodzi ze strefy wyprzedania (<30).
Sprzedaje gdy RSI opuszcza strefę wykupienia (>70).

### MACD
Kupuje gdy histogram MACD zmienia znak na dodatni.
Sprzedaje przy zmianie na ujemny.

## Architektura

```
main.py          # Punkt wejścia, parsowanie argumentów
bot.py           # Główna pętla bota
strategy.py      # Strategie: MA, RSI, MACD
risk_manager.py  # Zarządzanie ryzykiem i pozycjami
exchange.py      # Wrapper ccxt (spot orders, OHLCV)
config.py        # Konfiguracja z .env
logger.py        # Kolorowe logi
```

## Ostrzeżenie

Bot handlowy wiąże się z ryzykiem utraty środków. Używaj go na własną odpowiedzialność.
Zawsze testuj w trybie DRY_RUN przed przejściem na handel LIVE.
