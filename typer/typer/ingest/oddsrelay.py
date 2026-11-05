"""Adapter: OddsRelay API v2 (kursy na zywo bukmacherow i gield z UK i Irlandii).

Uzywamy GET /v2/odds/raw: ceny kazdego bukmachera i gieldy osobno (w tym Betfair Exchange),
strona po stronie. To nam daje snapshoty "w chwili typu" i "zamkniecia" do CLV.

Zasady API (oficjalny klient PyPI `oddsrelay` 0.1.1, kontrakt 2026-07-08, i dokumentacja):
- klucz z ODDSRELAY_KEY idzie tylko w naglowku Authorization: Bearer, nigdy w URL ani w logu,
- kazde wywolanie kosztuje tokeny, stan w naglowkach X-Tokens-Cost/Used/Remaining/Limit/Reset,
- 402 = brak tokenow (nie ponawiamy), 429 = poczekaj Retry-After, 5xx = ponow z opoznieniem,
- quote=true wycenia wywolanie bez wydawania tokenow,
- raw wymaga gzip (requests wysyla Accept-Encoding: gzip sam), strony przez meta.next_cursor.

Region "pl" nie istnieje: tylko region=uk.

UWAGA: kształt zdarzenia w /v2/odds/raw nie byl sprawdzony na zywo (host zablokowany w sesji
budowy). Wszystkie zalozenia o nazwach pol siedza w _venues() i _prices(), zeby po pierwszym
prawdziwym wywolaniu poprawic tylko te dwie funkcje i atrape w tests/fixtures.

Kontrakt dla CLV (uzgodniony): wiersz gieldy ma bookmaker="betfair_exchange", price = najlepszy
back, lay_price = najlepszy lay (NaN u bukmacherow), kind="close" dla 0..10 min przed startem.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

from typer import config
from typer.ingest.base import SourceUnavailable

log = logging.getLogger("typer.ingest.oddsrelay")
SOURCE = "oddsrelay"
BASE_URL = "https://api.oddsrelay.io"
KEY_ENV = "ODDSRELAY_KEY"
CLOSE_WINDOW_MIN = 10  # jak w odds_api: snapshot 0..10 min przed startem = zamkniecie
TOKENS_ALARM = 5000    # domyslny prog ostrzezenia, nadpisywany w sources.yaml (oddsrelay.tokens_alarm)
MAX_PAGES = 40         # bezpiecznik na petle stron (250 zdarzen na strone)
DRAW_NAMES = {"draw", "the draw", "x"}


class TokensExhausted(SourceUnavailable):
    """HTTP 402: skonczyly sie tokeny. Ponawianie nic nie da, czekamy na reset."""


def _cfg() -> dict:
    return config.sources().get("oddsrelay", {}) or {}


def _int(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return v  # np. "unlimited"


def tokens_from_headers(headers) -> dict:
    """Naglowki X-Tokens-*: cost, used, remaining, limit, reset. Brak naglowka = None."""
    h = {k.lower(): v for k, v in (headers or {}).items()}
    return dict(cost=_int(h.get("x-tokens-cost")), used=_int(h.get("x-tokens-used")),
                remaining=_int(h.get("x-tokens-remaining")), limit=_int(h.get("x-tokens-limit")),
                reset=h.get("x-tokens-reset"))


def tokens_low(tokens: dict, threshold: int | None = None) -> bool:
    """True, gdy zostalo mniej tokenow niz prog. "unlimited" albo brak naglowka = False."""
    threshold = _cfg().get("tokens_alarm", TOKENS_ALARM) if threshold is None else threshold
    rem = tokens.get("remaining")
    return isinstance(rem, int) and rem < threshold


def _error_code(r: requests.Response) -> str:
    try:
        err = r.json().get("error", {})
        return err.get("code") or err.get("message") or ""
    except ValueError:
        return ""


def request(path: str, params: dict | None = None, *, session: requests.Session | None = None,
            retries: int = 3, timeout: float = 60, sleep: Callable[[float], None] = time.sleep
            ) -> tuple[dict, dict]:
    """Jedno wywolanie API. Zwraca (cialo JSON, tokeny z naglowkow).

    Bledy trwale (400, 401, 403, 404) i 402 -> wyjatek od razu. 429 -> czekamy Retry-After.
    5xx i bledy sieci -> ponawiamy z wykladniczym opoznieniem. Odmowa proxy -> od razu wyjatek.
    """
    key = (config.env(KEY_ENV) or "").strip()
    if not key:
        raise SourceUnavailable(f"brak {KEY_ENV} w .env")
    url = (_cfg().get("url") or BASE_URL).rstrip("/") + path
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json",
               "Accept-Encoding": "gzip"}
    sess = session or requests.Session()
    delay, last_err = 2.0, None
    for attempt in range(retries + 1):
        try:
            r = sess.get(url, params=params, headers=headers, timeout=timeout,
                         allow_redirects=False)
        except requests.exceptions.ProxyError as e:
            raise SourceUnavailable(f"{SOURCE}: host zablokowany przez proxy ({type(e).__name__})") from e
        except requests.RequestException as e:
            last_err = f"{type(e).__name__}"
        else:
            tokens = tokens_from_headers(r.headers)
            if r.status_code == 200:
                log.info("%s %s: koszt %s, zostalo %s tokenow", SOURCE, path, tokens["cost"],
                         tokens["remaining"])
                if tokens_low(tokens):
                    log.warning("%s: zostalo tylko %s tokenow (reset %s)", SOURCE,
                                tokens["remaining"], tokens["reset"])
                return r.json(), tokens
            code = _error_code(r)
            if r.status_code == 402:
                raise TokensExhausted(f"{SOURCE}: brak tokenow ({code}), zostalo {tokens['remaining']}, "
                                      f"reset {tokens['reset']}")
            if r.status_code in (400, 401, 403, 404):
                raise SourceUnavailable(f"{SOURCE}: HTTP {r.status_code} {code} dla {path}")
            last_err = f"HTTP {r.status_code} {code}".strip()
            if r.status_code == 429 and attempt < retries:
                wait = float(r.headers.get("Retry-After") or delay)
                log.warning("%s: limit zapytan, czekam %.0fs", SOURCE, wait)
                sleep(wait)
                continue
        if attempt < retries:
            log.warning("%s: proba %d nieudana (%s), ponawiam za %.0fs", SOURCE, attempt + 1,
                        last_err, delay)
            sleep(delay)
            delay *= 2
    raise SourceUnavailable(f"{SOURCE}: {last_err}")


def quote(path: str, params: dict, **kw) -> int | None:
    """Ile tokenow kosztowaloby wywolanie (quote=true nie wydaje tokenow)."""
    body, _ = request(path, {**params, "quote": "true"}, **kw)
    return _int(body.get("cost"))


def download(now: datetime | None = None, *, sports: str = "soccer", markets: str = "h2h",
             region: str = "uk", max_tokens: int | None = None, raw_dir: Path | None = None,
             **kw) -> tuple[list[dict], dict]:
    """Wszystkie strony /v2/odds/raw dla sportu. Zwraca (zdarzenia, tokeny po ostatniej stronie,
    z polem spent = suma kosztow). Snapshot trafia do raw/oddsrelay/, to jest nasza historia kursow.

    max_tokens: najpierw wycena pierwszej strony; gdy drozsza, nic nie pobieramy."""
    now = now or datetime.now(timezone.utc)
    params = dict(region=region, sports=sports, markets=markets, oddsFormat="decimal")
    max_tokens = _cfg().get("max_tokens_per_call") if max_tokens is None else max_tokens
    if max_tokens:
        cost = quote("/v2/odds/raw", params, **kw)
        if isinstance(cost, int) and cost > max_tokens:
            raise SourceUnavailable(f"{SOURCE}: wywolanie kosztuje {cost} tokenow, limit {max_tokens}")
    events, spent, cursor, tokens = [], 0, None, {}
    for _ in range(MAX_PAGES):
        body, tokens = request("/v2/odds/raw", {**params, **({"cursor": cursor} if cursor else {})}, **kw)
        events.extend(body.get("data") or [])
        spent += tokens["cost"] if isinstance(tokens.get("cost"), int) else 0
        cursor = (body.get("meta") or {}).get("next_cursor")
        if not cursor:
            break
    else:
        log.warning("%s: przerwano po %d stronach", SOURCE, MAX_PAGES)
    path = (raw_dir or config.RAW_DIR) / SOURCE / f"{sports}_{markets}_{now:%Y%m%dT%H%M}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(dict(snapshot_utc=now.isoformat(), data=events), ensure_ascii=False))
    tmp.replace(path)
    return events, {**tokens, "spent": spent}


# --- parser: tu siedza wszystkie zalozenia o ksztalcie odpowiedzi ---

def _venues(ev: dict):
    """(klucz venue, czy gielda, rynki) dla bukmacherow i gield zdarzenia."""
    for group, is_ex in (("bookmakers", False), ("exchanges", True)):
        for v in ev.get(group) or []:
            k = v.get("key") or v.get("bookmaker") or v.get("exchange")
            if k:
                yield k, is_ex or v.get("type") == "exchange", v.get("markets") or []


def _best(levels, side: str):
    """Najlepsza cena z listy poziomow [{price, ...}]: back = najwyzsza, lay = najnizsza."""
    prices = [float(x["price"]) for x in levels or [] if isinstance(x, dict) and x.get("price")]
    if not prices:
        return None
    return max(prices) if side == "back" else min(prices)


def _prices(o: dict) -> tuple[float | None, float | None]:
    """(back, lay) z wyniku. Bukmacher: price. Gielda: back/lay jako liczba albo lista poziomow."""
    back = o.get("price") or o.get("back_price")
    lay = o.get("lay_price")
    if back is None and o.get("back") is not None:
        back = o["back"] if isinstance(o["back"], (int, float)) else _best(o["back"], "back")
    if lay is None and o.get("lay") is not None:
        lay = o["lay"] if isinstance(o["lay"], (int, float)) else _best(o["lay"], "lay")
    return (float(back) if back else None), (float(lay) if lay else None)


def competition(ev: dict) -> str | None:
    return ev.get("competition_key") or ev.get("competition") or ev.get("sport_key")


def parse(events: list[dict], snapshot_utc: datetime, leagues: dict[str, str] | None = None
          ) -> pd.DataFrame:
    """Plaska tabela jak w odds_api.parse plus lay_price i source.

    leagues: mapowanie klucz rozgrywek OddsRelay -> kod ligi (np. E0). Bez mapowania league =
    klucz rozgrywek. Rynki inne niz h2h i zdarzenia bez druzyn (np. outrighty) pomijamy."""
    snap = pd.Timestamp(snapshot_utc)
    rows = []
    for ev in events:
        home, away = ev.get("home_team"), ev.get("away_team")
        if not home or not away or not ev.get("commence_time"):
            continue
        ko = pd.Timestamp(ev["commence_time"])
        ko = ko.tz_localize("UTC") if ko.tzinfo is None else ko.tz_convert("UTC")
        mins = (ko - snap).total_seconds() / 60
        comp = competition(ev)
        league = (leagues or {}).get(comp, comp)
        kind = "close" if 0 <= mins <= CLOSE_WINDOW_MIN else ("taken" if mins > 0 else "inplay")
        for venue, is_ex, markets in _venues(ev):
            for m in markets:
                if m.get("key") != "h2h":
                    continue
                for o in m.get("outcomes") or []:
                    name = o.get("name")
                    sel = ("1" if name == home else "2" if name == away else
                           "X" if str(name).lower() in DRAW_NAMES else None)
                    back, lay = _prices(o)
                    if sel is None or back is None:
                        continue
                    rows.append(dict(league=league, source=SOURCE, source_event_id=ev.get("id"),
                                     home_raw=home, away_raw=away, kickoff_utc=ko, bookmaker=venue,
                                     is_exchange=is_ex, market="1X2", selection=sel, line=None,
                                     price=back, lay_price=lay if is_ex else float("nan"),
                                     snapshot_utc=snap, minutes_to_kickoff=mins, kind=kind))
    return pd.DataFrame(rows)
