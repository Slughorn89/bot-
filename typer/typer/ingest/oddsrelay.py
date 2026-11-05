"""OddsRelay (https://api.oddsrelay.io, kontrakt v2): pobieranie z kontrola kosztu w tokenach.

Kazde zapytanie najpierw z quote=true (darmowe: zwraca koszt), potem budzet (typer/ingest/budget.py),
dopiero potem prawdziwe wywolanie. Uzycie zapisywane z naglowka x-tokens-remaining.
Autoryzacja: Authorization: Bearer <ODDSRELAY_KEY> (klucz w .env, nigdy w repo).
Dwa zrodla danych:
  raw_odds    /v2/odds/raw: biezace kursy per bukmacher (snapshot "w chwili typu"),
  closing     /v2/historical/closing: zamkniecia dnia (bukmacherzy: close_price, gieldy: back/lay).
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


def raw_odds(sport_key: str, *, bookmakers: str | None = None, markets: str = "h2h,totals",
             now: datetime | None = None, ledger=None) -> bytes:
    now = now or datetime.now(timezone.utc)
    bk = bookmakers or ",".join(_cfg().get("bukmacherzy_typ", ["bet365"]))
    params = dict(region=_cfg().get("region", "uk"), sport=sport_key, bookmakers=bk, markets=markets,
                  oddsFormat="decimal", dateFormat="iso", inPlay="exclude", limit=250)
    return _get("/v2/odds/raw", params, f"raw_{sport_key}_{now:%Y%m%dT%H%M}.json", max_age_hours=0.2,
                now=now, ledger=ledger, note=f"raw {sport_key} {bk} {markets}")


def closing(day: date, sport_key: str, *, exchanges: str | None = None, bookmakers: str | None = None,
            markets: str = "h2h,totals", now: datetime | None = None, ledger=None) -> bytes:
    """Wszystkie strony zamkniec dnia sklejone w jedna odpowiedz {meta, data}."""
    now = now or datetime.now(timezone.utc)
    ex = exchanges or ",".join(_cfg().get("gieldy_zamkniecie", ["betfair_exchange"]))
    bk = bookmakers or ",".join(_cfg().get("bukmacherzy_typ", ["bet365"]))
    data, cursor, meta, page = [], None, {}, 0
    while True:
        params = dict(date=f"{day:%Y-%m-%d}", sports=sport_key, region="uk", exchanges=ex, bookmakers=bk,
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
