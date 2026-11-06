"""TheStatsAPI (https://api.thestatsapi.com/api, v1): pobieranie z kontrola limitow.

Autoryzacja: Authorization: Bearer <THESTATSAPI_KEY> (klucz w .env, nigdy w repo).
Limity z naglowkow kazdej odpowiedzi: X-RateLimit-* (na minute) i X-Monthly-Quota-* (na cykl). Limit na minute
pilnuje token bucket (sources.yaml: limit_na_minute), miesieczny: ledger (budget.py), 1 zapytanie = 1 jednostka.
Licencja (thestatsapi.com/terms): uzycie we wlasnej aplikacji; bez odsprzedazy i publikacji hurtowej; cache
tylko w zakresie potrzebnym do dzialania. Surowe odpowiedzi zostaja lokalnie w raw/ (poza repo).

Mecz to paczka 5 odpowiedzi (mecz, przebieg, statystyki, kursy, sklady) sklejona w jeden JSON dla adaptera.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from typer import config
from typer.ingest.base import SourceUnavailable, fetch

SOURCE = "thestatsapi"
PARTS = ("", "/timeline", "/stats", "/odds", "/lineups")


def _cfg() -> dict:
    return config.sources()[SOURCE]


def _headers() -> dict:
    key = config.env("THESTATSAPI_KEY")
    if not key:
        raise SourceUnavailable("brak THESTATSAPI_KEY w .env")
    return {"Authorization": f"Bearer {key}"}


def get(path: str, params: dict | None, cache_name: str, *, max_age_hours=None, ledger=None,
        now: datetime | None = None) -> dict:
    from typer.ingest.budget import Ledger
    now = now or datetime.now(timezone.utc)
    ledger = ledger or Ledger()
    if not ledger.can_spend(SOURCE, 1, now):
        raise SourceUnavailable(f"budzet TheStatsAPI wyczerpany ({ledger.used(SOURCE, now)} zapytan w cyklu)")
    meta: dict = {}
    raw = fetch(_cfg()["url"] + path, SOURCE, cache_name, params=params, headers=_headers(),
                max_age_hours=max_age_hours, meta=meta)
    if not meta.get("cache"):
        ledger.record(SOURCE, 1, now, meta.get("headers"), note=path)
    return json.loads(raw)


def matches(competition_id: str, season_id: str | None = None, *, date_from: str | None = None,
            date_to: str | None = None, status: str | None = "finished", ledger=None) -> list[dict]:
    """Wszystkie strony listy meczow (100 na strone)."""
    out, page = [], 1
    while True:
        params = dict(competition_id=competition_id, per_page=100, page=page, sort="utc_date")
        for k, v in (("season_id", season_id), ("date_from", date_from), ("date_to", date_to), ("status", status)):
            if v:
                params[k] = v
        tag = season_id or f"{date_from}_{date_to}"
        js = get("/football/matches", params, f"matches_{competition_id}_{tag}_{status}_{page}.json",
                 max_age_hours=None if status == "finished" and season_id else 6, ledger=ledger)
        out.extend(js.get("data", []))
        if page >= int(js.get("meta", {}).get("total_pages", 1)):
            return out
        page += 1


def match_bundle(match_id: str, parts=PARTS, ledger=None) -> bytes:
    """Mecz rozegrany: paczka (mecz, przebieg, statystyki, kursy, sklady). Brak czesci (404) = pole puste."""
    out = {"match_id": match_id}
    for p in parts:
        name = p.strip("/") or "match"
        try:
            out[name] = get(f"/football/matches/{match_id}{p}", None, f"{match_id}_{name}.json", ledger=ledger
                            ).get("data")
        except SourceUnavailable as e:
            if "404" not in str(e):
                raise
            out[name] = None
    return json.dumps(out).encode()
