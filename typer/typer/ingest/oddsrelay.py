"""OddsRelay (https://api.oddsrelay.io, kontrakt v2): pobieranie z kontrola kosztu w tokenach.

Kazde zapytanie najpierw z quote=true (darmowe: zwraca koszt), potem budzet (typer/ingest/budget.py),
dopiero potem prawdziwe wywolanie. Uzycie zapisywane z naglowka x-tokens-remaining.
Autoryzacja: Authorization: Bearer <ODDSRELAY_KEY> (klucz w .env, nigdy w repo).
Dwa zrodla danych:
  raw_odds    /v2/odds/raw: biezace kursy per bukmacher (snapshot "w chwili typu"),
  closing     /v2/historical/closing: zamkniecia dnia, TYLKO bukmacherzy (close_price).
Archiwum nie ma gield: gielda w `exchanges` albo exchangesOnly=true daje 403 exchange_history_unavailable
(oddsrelay.io/products/historical-odds, sprawdzone 2026-11-05). Zamkniecie Betfair zbieramy wiec sami:
snapshot raw z gielda (ponizej `exchanges`) w oknie 10 min przed startem.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from typer import config
from typer.ingest.base import SourceUnavailable, fetch

SOURCE = "oddsrelay"


def _cfg() -> dict:
    return config.sources()[SOURCE]


def _headers() -> dict:
    key = config.env("ODDSRELAY_KEY")
    if not key:
        raise SourceUnavailable("brak ODDSRELAY_KEY w .env")
    return {"Authorization": f"Bearer {key}", "Accept-Encoding": "gzip"}


def quote_cost(path: str, params: dict) -> int:
    """Koszt zapytania w tokenach (quote=true nic nie kosztuje)."""
    raw = fetch(_cfg()["url"] + path, SOURCE, "quote.json", params=dict(params, quote="true"), headers=_headers(),
                max_age_hours=0)
    q = json.loads(raw)
    if "cost" not in q:
        raise SourceUnavailable(f"OddsRelay: odpowiedz quote bez pola cost: {str(q)[:200]}")
    return int(q["cost"])


def _get(path: str, params: dict, cache_name: str, *, max_age_hours, now: datetime, ledger, note: str) -> bytes:
    from typer.ingest.budget import Ledger
    ledger = ledger or Ledger()
    cost = quote_cost(path, params)
    if not ledger.can_spend(SOURCE, cost, now):
        raise SourceUnavailable(f"budzet OddsRelay wyczerpany ({ledger.used(SOURCE, now)} tokenow w okresie, "
                                f"koszt zapytania {cost})")
    meta: dict = {}
    raw = fetch(_cfg()["url"] + path, SOURCE, cache_name, params=params, headers=_headers(),
                max_age_hours=max_age_hours, meta=meta)
    if not meta.get("cache"):
        ledger.record(SOURCE, cost, now, meta.get("headers"), note=note)
    return raw


def raw_odds(sport_key: str, *, bookmakers: str | None = None, exchanges: str | None = None,
             markets: str = "h2h,totals", now: datetime | None = None, ledger=None) -> bytes:
    """Biezace kursy bukmacherow (kurs w chwili typu) i gield (zamkniecie Betfair do CLV, bo archiwum
    gield nie ma). exchanges="" wylacza gieldy."""
    now = now or datetime.now(timezone.utc)
    bk = bookmakers or ",".join(_cfg().get("bukmacherzy_typ", ["bet365"]))
    ex = ",".join(_cfg().get("gieldy_zamkniecie", ["betfair_exchange"])) if exchanges is None else exchanges
    params = dict(region=_cfg().get("region", "uk"), sport=sport_key, bookmakers=bk, markets=markets,
                  oddsFormat="decimal", dateFormat="iso", inPlay="exclude", limit=250)
    if ex:
        params["exchanges"] = ex
    return _get("/v2/odds/raw", params, f"raw_{sport_key}_{now:%Y%m%dT%H%M}.json", max_age_hours=0.2,
                now=now, ledger=ledger, note=f"raw {sport_key} {bk} {markets}")


def closing(day: date, sport_key: str, *, bookmakers: str | None = None,
            markets: str = "h2h,totals", now: datetime | None = None, ledger=None) -> bytes:
    """Wszystkie strony zamkniec dnia (tylko bukmacherzy) sklejone w jedna odpowiedz {meta, data}.
    Bez parametru exchanges: z nim API odrzuca cale zapytanie (403 exchange_history_unavailable)."""
    now = now or datetime.now(timezone.utc)
    bk = bookmakers or ",".join(_cfg().get("bukmacherzy_typ", ["bet365"]))
    data, cursor, meta, page = [], None, {}, 0
    while True:
        params = dict(date=f"{day:%Y-%m-%d}", sports=sport_key, region="uk", bookmakers=bk,
                      markets=markets, limit=50)
        if cursor:
            params["cursor"] = cursor
        raw = _get("/v2/historical/closing", params, f"closing_{sport_key}_{day:%Y%m%d}_{page}.json",
                   max_age_hours=None, now=now, ledger=ledger, note=f"closing {sport_key} {day}")
        js = json.loads(raw)
        meta = js.get("meta", {})
        data.extend(js.get("data", []))
        cursor = meta.get("next_cursor")
        page += 1
        if not cursor or page > 40:
            break
    meta = dict(meta, count=len(data), next_cursor=None)
    return json.dumps(dict(meta=meta, data=data)).encode()
