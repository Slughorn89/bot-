"""Adapter: OddsRelay /v2/historical/closing (kursy zamkniecia bukmacherow UK z archiwum).

Co mowi dokumentacja (oddsrelay.io/products/historical-odds, sprawdzone 2026-11-05):
* historia to TYLKO bukmacherzy. Gielda w `exchanges` albo `exchangesOnly=true` daje
  403 `exchange_history_unavailable`, a pola `close_back_price`/`close_lay_price` sa null.
  Zamkniecie Betfair zbieramy wiec sami ze snapshotow na zywo (adapter typer/ingest/oddsrelay.py,
  bookmaker="betfair_exchange", kind="close").
* archiwum od 2026-10-17, poprzedni dzien UTC dochodzi w nocy.
* parametry: date (dzien UTC), sports (wymagane), bookmakers, markets, limit (do 50), cursor, region.
* odpowiedz: event -> bookmakers -> markets -> outcomes; outcome ma name, ord, open_price,
  close_price, close_at, high, low, moves.

Dokladne nazwy kluczy (np. `key` bukmachera, `point` linii totals) wzielismy z opisu, bez dostepu
do API (host zablokowany w sesji budowy). Parser jest wiec tolerancyjny i pomija to, czego nie zna.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date

import pandas as pd

from typer.ingest.base import SourceUnavailable

log = logging.getLogger("typer.ingest.oddsrelay_closing")
SOURCE = "oddsrelay_hist"
PATH = "/v2/historical/closing"
ARCHIVE_START = date(2026, 10, 17)
DRAW = {"draw", "x", "the draw", "remis"}


def _sel_1x2(name: str, home: str, away: str) -> str | None:
    n = (name or "").strip()
    if n == home or n.lower() in {"home", "1"}:
        return "1"
    if n == away or n.lower() in {"away", "2"}:
        return "2"
    if n.lower() in DRAW:
        return "X"
    return None


def parse(raw: bytes | dict) -> pd.DataFrame:
    """Plaska tabela: jeden wiersz = mecz x bukmacher x rynek x selekcja (kurs zamkniecia)."""
    body = json.loads(raw) if isinstance(raw, (bytes, str)) else raw
    events = body.get("data", body) if isinstance(body, dict) else body
    rows = []
    for ev in events or []:
        home, away = ev.get("home_team"), ev.get("away_team")
        if not home or not away:
            continue
        ko = pd.Timestamp(ev["commence_time"])
        ko = ko.tz_localize("UTC") if ko.tzinfo is None else ko.tz_convert("UTC")
        for bk in ev.get("bookmakers", []):
            book = bk.get("key") or bk.get("bookmaker") or bk.get("name")
            if not book:
                continue
            for m in bk.get("markets", []):
                mkey = m.get("key") or m.get("market")
                for o in m.get("outcomes", []):
                    price = o.get("close_price")
                    if price is None or not price > 1:
                        continue
                    if mkey == "h2h":
                        sel, market, line = _sel_1x2(o.get("name"), home, away), "1X2", None
                    elif mkey == "totals":
                        point = o.get("point", m.get("point"))
                        if point is None:
                            continue
                        line = float(point)
                        side = (o.get("name") or "").lower()
                        if side not in ("over", "under"):
                            continue
                        market, sel = f"OU{line:g}", f"{side}{line:g}"
                    else:
                        continue
                    if sel is None:
                        continue
                    rows.append(dict(source_event_id=str(ev.get("id")), home_raw=home, away_raw=away,
                                     kickoff_utc=ko, bookmaker=str(book), market=market, selection=sel,
                                     line=line, price=float(price), open_price=o.get("open_price"),
                                     close_at=o.get("close_at"), moves=o.get("moves"), kind="close"))
    return pd.DataFrame(rows)


def download_day(day: date | str, request: Callable[[str, dict], tuple[dict, dict]], *,
                 sports: str = "soccer", markets: str = "h2h,totals", region: str = "uk",
                 bookmakers: str | None = None, max_pages: int = 100) -> list[dict]:
    """Wszystkie strony zamkniec z jednego dnia UTC. `request(path, params) -> (body, tokens)`
    to klient z typer/ingest/oddsrelay.py (klucz, gzip, limity tokenow); tu go nie dublujemy."""
    d = pd.Timestamp(day).date()
    if d < ARCHIVE_START:
        raise SourceUnavailable(f"archiwum OddsRelay zaczyna sie {ARCHIVE_START}, a prosisz o {d}")
    params = dict(date=d.isoformat(), sports=sports, markets=markets, region=region, limit=50)
    if bookmakers:
        params["bookmakers"] = bookmakers
    events, cursor = [], None
    for _ in range(max_pages):
        p = dict(params, cursor=cursor) if cursor else params
        body, tokens = request(PATH, p)
        events.extend(body.get("data", []) if isinstance(body, dict) else body)
        cursor = (body.get("meta") or {}).get("next_cursor") if isinstance(body, dict) else None
        if tokens:
            log.info("closing %s: tokeny %s", d, tokens)
        if not cursor:
            break
    else:
        log.warning("closing %s: przerwane po %d stronach", d, max_pages)
    return events
