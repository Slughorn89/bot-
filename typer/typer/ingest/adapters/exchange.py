"""Adapter: Betfair Exchange API (kursy back/lay, ostatnia cena, wolumen w czasie).

DOMYSLNIE WYLACZONY (config/sources.yaml: betfair.wlaczony: false). Wymaga konta Betfair i klucza
aplikacji, a Betfair Exchange nie musi byc legalnie dostepny w Twoim kraju (w Polsce prawdopodobnie
nie jest, do sprawdzenia). Wlaczasz go dopiero po potwierdzeniu legalnego dostepu.

Dwa formaty wejscia:
  stream   komunikaty Exchange Stream API i pliki Betfair Historical Data (JSON w liniach, op=mcm):
           available_at = pt (czas publikacji komunikatu). To jedyne zrodlo "kursu i wolumenu w czasie".
  rest     odpowiedz listMarketBook (JSON-RPC): available_at = chwila pobrania (REST nie podaje czasu ceny).
W strumieniu rc to zmiany (delty): pola, ktorych nie ma w komunikacie, zostaja puste.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from typer import config
from typer.ingest.core.adapter import Adapter, RawPayload, register
from typer.ingest.core.http import SourceUnavailable
from typer.ingest.core.records import ExchangeTick
from typer.ingest.schema import ContractError

RPC = "https://api.betfair.com/exchange/betting/json-rpc/v1"
LOGIN = "https://identitysso.betfair.com/api/login"


@register
class BetfairExchange(Adapter):
    name = "betfair"
    license = "Betfair API Terms; wymaga konta i legalnego dostepu w kraju uzytkownika"
    enabled_by_default = False
    record_types = (ExchangeTick,)

    def _session(self) -> dict:  # pragma: no cover - wymaga konta
        app, user, pwd = (config.env("BETFAIR_APP_KEY"), config.env("BETFAIR_USERNAME"),
                          config.env("BETFAIR_PASSWORD"))
        if not (app and user and pwd):
            raise SourceUnavailable("brak BETFAIR_APP_KEY / BETFAIR_USERNAME / BETFAIR_PASSWORD w .env")
        r = self.client.session.post(LOGIN, data=dict(username=user, password=pwd),
                                     headers={"X-Application": app, "Accept": "application/json"}, timeout=30)
        tok = r.json().get("token")
        if not tok:
            raise SourceUnavailable(f"Betfair login: {r.json().get('error')}")
        return {"X-Application": app, "X-Authentication": tok, "Content-Type": "application/json"}

    def fetch(self, market_ids: list[str] | None = None, stream_files: list[str] | None = None) -> list[RawPayload]:
        out = []
        for path in stream_files or []:  # pliki Historical Data / zapis strumienia
            with open(path, "rb") as f:
                out.append(RawPayload(path, f.read(), datetime.now(timezone.utc), dict(format="stream")))
        if market_ids:  # pragma: no cover - wymaga konta
            headers = self._session()
            body = dict(jsonrpc="2.0", method="SportsAPING/v1.0/listMarketBook", id=1,
                        params=dict(marketIds=market_ids,
                                    priceProjection=dict(priceData=["EX_BEST_OFFERS", "EX_TRADED"])))
            name = f"marketbook_{'_'.join(market_ids)}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.json"
            r = self.client.get(RPC, name, headers=headers, method="POST", json_body=body, max_age_hours=0)
            out.append(RawPayload(name, r.content, r.fetched_at, dict(format="rest")))
        return out

    def parse(self, payload: RawPayload) -> list:
        return self._stream(payload) if payload.ctx.get("format") == "stream" else self._rest(payload)

    def _stream(self, payload: RawPayload) -> list:
        out = []
        for ln, line in enumerate(payload.content.decode().splitlines()):
            if not line.strip():
                continue
            msg = json.loads(line)
            if msg.get("op") != "mcm":
                continue
            if "pt" not in msg:
                raise ContractError("Betfair stream: brak pt (czasu publikacji)")
            pt = datetime.fromtimestamp(msg["pt"] / 1000, timezone.utc)
            for mc in msg.get("mc", []):
                md = mc.get("marketDefinition") or {}
                for rc in mc.get("rc", []):
                    batb, batl = rc.get("batb") or [], rc.get("batl") or []
                    best = lambda lv: min((x for x in lv if x[0] == 0), default=None, key=lambda x: x[0])
                    b, l_ = best(batb), best(batl)
                    out.append(ExchangeTick(
                        source=self.name, license=self.license,
                        source_key=f"bf:{mc['id']}:{rc['id']}:{msg['pt']}:{ln}", available_at=pt,
                        fetched_at=max(payload.fetched_at, pt), market_id=str(mc["id"]), selection_id=str(rc["id"]),
                        ts=pt, market_type=md.get("marketType"), event_name=md.get("eventName"),
                        back=b[1] if b and b[1] > 1 else None, lay=l_[1] if l_ and l_[1] > 1 else None,
                        ltp=rc.get("ltp"), traded_volume=rc.get("tv")))
        return out

    def _rest(self, payload: RawPayload) -> list:
        body = json.loads(payload.content)
        if "result" not in body:
            raise ContractError(f"Betfair REST: brak 'result' ({str(body.get('error'))[:200]})")
        ts = payload.fetched_at
        out = []
        for mb in body["result"]:
            for r in mb.get("runners", []):
                ex = r.get("ex") or {}
                b = (ex.get("availableToBack") or [{}])[0].get("price")
                l_ = (ex.get("availableToLay") or [{}])[0].get("price")
                out.append(ExchangeTick(
                    source=self.name, license=self.license,
                    source_key=f"bf:{mb['marketId']}:{r['selectionId']}:{ts:%Y%m%dT%H%M%S}", available_at=ts,
                    fetched_at=ts, market_id=mb["marketId"], selection_id=str(r["selectionId"]), ts=ts,
                    back=b, lay=l_, ltp=r.get("lastPriceTraded"), traded_volume=r.get("totalMatched")))
        return out
