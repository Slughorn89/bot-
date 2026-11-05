"""Adapter OddsRelay: kursy bukmacherow UK (bet365) w chwili typu i zamkniecia gield do CLV.

available_at:
  * snapshot /v2/odds/raw: chwila snapshotu (kurs jest publiczny i aktualny wtedy, kiedy go widzimy);
    mecz trwajacy pomijamy; do 10 min przed startem kind = "close", wczesniej "taken",
  * zamkniecie /v2/historical/closing: close_at (ostatnia cena przed startem). Cena z close_at po starcie
    to cena w trakcie meczu, a nie zamkniecie: odrzucana (licznik self.skipped).
Gielda (betfair_exchange, matchbook, smarkets): kurs zamkniecia = srodek miedzy "za" i "przeciw"
w prawdopodobienstwie, 1 / ((1/back + 1/lay) / 2); prowizja gieldy to nie marza bukmachera.
Selekcje: h2h -> 1X2 (gospodarz "1", remis "X", gosc "2"), totals z linia -> OU<linia>.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from typer import config
from typer.ingest.core.adapter import Adapter, RawPayload, register
from typer.ingest.core.records import OddsQuote
from typer.ingest.schema import ContractError

CLOSE_WINDOW = timedelta(minutes=10)
EXCHANGES = {"betfair_exchange", "matchbook", "smarkets"}


def sport_key(league: str) -> str | None:
    meta = config.leagues().get(league, {})
    return meta.get("oddsrelay") or meta.get("odds_api")    # klucze sportow jak w The Odds API (do potwierdzenia)


def _league_for(sport: str, ctx: dict) -> str | None:
    if ctx.get("league"):
        return ctx["league"]
    for lg in config.leagues():
        if sport_key(lg) == sport:
            return lg
    return None


def _selection(market: str, o: dict, home: str, away: str):
    if market == "h2h":
        return "1X2", ("1" if o["name"] == home else "2" if o["name"] == away else "X"), None
    if market == "totals" and o.get("point") is not None:
        line = float(o["point"])
        return f"OU{line:g}", f"{o['name'].lower()}{line:g}", line
    return None


def exchange_mid(back, lay) -> float | None:
    if back and lay and back > 1 and lay > 1:
        return 1.0 / ((1.0 / back + 1.0 / lay) / 2.0)
    return None


@register
class OddsRelay(Adapter):
    name = "oddsrelay"
    license = "OddsRelay: komercyjna B2B (kursy UK i gieldy)"
    record_types = (OddsQuote,)

    def __init__(self):
        super().__init__()
        self.skipped = 0

    def fetch(self, leagues: list[str] | None = None, mode: str = "raw", day: date | None = None) -> list[RawPayload]:
        from typer.ingest import oddsrelay as api
        out = []
        for lg in leagues or list(config.leagues()):
            sk = sport_key(lg)
            if not sk:
                continue
            now = datetime.now(timezone.utc)
            raw = api.raw_odds(sk, now=now) if mode == "raw" else api.closing(day or now.date(), sk, now=now)
            out.append(RawPayload(f"{mode}_{sk}.json", raw, now, dict(league=lg)))
        return out

    def parse(self, payload: RawPayload) -> list:
        js = json.loads(payload.content)
        if not isinstance(js, dict) or "data" not in js:
            raise ContractError(f"OddsRelay: oczekiwany obiekt z polem data: {str(js)[:200]}")
        feed = (js.get("meta") or {}).get("feed_type", "raw")
        snap = payload.fetched_at
        out = []
        for ev in js["data"]:
            missing = {"commence_time", "home_team", "away_team", "bookmakers"} - set(ev)
            if missing:
                raise ContractError(f"OddsRelay: brak pol {sorted(missing)}")
            lg = _league_for(ev.get("sport_key", ""), payload.ctx)
            if lg is None:
                continue
            ko = pd.Timestamp(ev["commence_time"]).tz_convert("UTC").to_pydatetime()
            home, away = ev["home_team"], ev["away_team"]
            eid = ev.get("id") or ev.get("event_id")
            if feed != "historical_closing" and ko <= snap:
                continue                               # mecz trwa albo sie skonczyl
            for bk in ev["bookmakers"]:
                for m in bk.get("markets", []):
                    for o in m.get("outcomes", []):
                        sel = _selection(m["key"], o, home, away)
                        if sel is None:
                            continue
                        market, selection, line = sel
                        if feed == "historical_closing":
                            rec = self._closing(o, bk["key"], ko, snap)
                            if rec is None:
                                continue
                            price, avail, kind = rec
                        else:
                            price, avail = o.get("price"), snap
                            kind = "close" if ko - snap <= CLOSE_WINDOW else "taken"
                        if not price or price <= 1:
                            continue
                        out.append(OddsQuote(
                            source=self.name, license=self.license, league=lg, kickoff_utc=ko, home=home, away=away,
                            source_key=f"{eid}:{bk['key']}:{market}:{selection}:{feed}:{avail:%Y%m%dT%H%M%S}",
                            available_at=avail, fetched_at=snap, bookmaker=bk["key"], market=market,
                            selection=selection, line=line, price=float(price), kind=kind))
        return out

    def _closing(self, o: dict, book: str, ko: datetime, snap: datetime):
        if not o.get("close_at"):
            self.skipped += 1
            return None
        at = pd.Timestamp(o["close_at"]).tz_convert("UTC").to_pydatetime()
        if at > ko + timedelta(seconds=60) or at < ko - timedelta(minutes=15):
            self.skipped += 1                          # cena w trakcie meczu albo stara: to nie zamkniecie
            return None
        if book in EXCHANGES:
            price = exchange_mid(o.get("close_back_price"), o.get("close_lay_price"))
        else:
            price = o.get("close_price")
        if price is None:
            self.skipped += 1
            return None
        return price, min(at, snap), "close"
