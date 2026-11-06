"""Adapter TheStatsAPI: mecz rozegrany -> wynik, statystyki druzyn (xG, strzaly, rozne, posiadanie), zdarzenia
z minutami (gole, kartki, rozne), sklady, kursy przedmeczowe.

available_at:
  * dane pomeczowe: min(start + 2h15, fetched_at) (jak API-Football),
  * sklady pobrane po fakcie: start - 60 min, szacunek (oficjalne sklady sa publiczne ok. godzine przed meczem),
  * kursy: `last_seen` = ostatnia cena przed meczem -> kind "close", available_at = start (szacunek, zrodlo nie
    podaje chwili); `opening` -> kind "bench" (moment publikacji nieznany, wiec NIGDY nie jako kurs "wziety").
Rozny: zrodlo podaje druzyne, ktora rozny ODDALA; w rekordzie team = druzyna WYKONUJACA (odwrocone),
zgodnie z /stats corner_kicks. Selekcje: 1X2, OU<linia> (gole), CORNERS<linia> (rozne lacznie), BTTS.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

from typer import config
from typer.ingest.core.adapter import Adapter, RawPayload, register
from typer.ingest.core.records import (POST_MATCH_LAG, LineupEntry, MatchEvent, MatchResult, OddsQuote,
                                       TeamMatchStats)
from typer.ingest.schema import ContractError

LINEUP_LEAD = timedelta(minutes=60)
EVENT_TYPES = {"goal": "goal", "own_goal": "own_goal", "penalty_scored": "penalty_scored",
               "penalty_missed": "penalty_missed", "yellow_card": "yellow", "second_yellow_card": "second_yellow",
               "red_card": "red", "corner_kick": "corner"}
BOOK_SLUG = {"Bet365": "bet365", "Pinnacle": "pinnacle", "Betfair Exchange": "betfair_exchange",
             "Paddy Power": "paddy_power", "BetMGM UK": "betmgm_uk"}


def _league(competition_id: str, ctx: dict) -> str | None:
    if ctx.get("league"):
        return ctx["league"]
    for lg, cid in (config.sources().get("thestatsapi", {}).get("ligi") or {}).items():
        if cid == competition_id:
            return lg
    return None


def _num(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _stat(stats: dict, key: str, side: str):
    v = ((stats or {}).get("overview") or {}).get(key, {})
    v = (v.get("all") or {}).get(side) if isinstance(v, dict) else None
    return _num(v)


@register
class TheStatsAPI(Adapter):
    name = "thestatsapi"
    license = "TheStatsAPI: komercyjna, uzycie we wlasnej aplikacji, bez redystrybucji"
    record_types = (MatchResult, TeamMatchStats, MatchEvent, LineupEntry, OddsQuote)

    def fetch(self, league: str, season_id: str | None = None, date_from: str | None = None,
              date_to: str | None = None, limit: int | None = None) -> list[RawPayload]:
        from datetime import datetime, timezone
        from typer.ingest import thestatsapi as api
        cid = (config.sources()["thestatsapi"].get("ligi") or {})[league]
        ms = api.matches(cid, season_id, date_from=date_from, date_to=date_to)
        out = []
        for m in ms[:limit] if limit else ms:
            raw = api.match_bundle(m["id"])
            out.append(RawPayload(f"{m['id']}.json", raw, datetime.now(timezone.utc), dict(league=league)))
        return out

    def parse(self, payload: RawPayload) -> list:
        b = json.loads(payload.content)
        m = b.get("match")
        if not m:
            raise ContractError(f"TheStatsAPI: paczka bez meczu: {str(b)[:200]}")
        for k in ("id", "utc_date", "home_team", "away_team", "status", "score"):
            if k not in m:
                raise ContractError(f"TheStatsAPI: brak pola {k}")
        lg = _league(m.get("competition_id", ""), payload.ctx)
        if lg is None or m["status"] != "finished":
            return []
        ko = pd.Timestamp(m["utc_date"]).tz_convert("UTC").to_pydatetime()
        fetched = payload.fetched_at
        post = min(ko + POST_MATCH_LAG, fetched)
        home, away = m["home_team"]["name"], m["away_team"]["name"]
        hid = m["home_team"]["id"]
        base = dict(source=self.name, license=self.license, league=lg, kickoff_utc=ko, home=home, away=away,
                    fetched_at=fetched)
        sc = m["score"]
        reg = sc.get("regulation") or sc
        out = [MatchResult(**base, source_key=f"{m['id']}:result", available_at=post,
                           fthg=int(reg["home"]), ftag=int(reg["away"]),
                           hthg=sc.get("half_time_home"), htag=sc.get("half_time_away"))]
        st = b.get("stats")
        if st:
            for side, team in (("home", home), ("away", away)):
                pos = _stat(st, "ball_possession", side)
                out.append(TeamMatchStats(
                    **base, source_key=f"{m['id']}:stats:{side}", available_at=post, team=team, side=side,
                    xg=_stat(st, "expected_goals", side), shots=_int(_stat(st, "total_shots", side)),
                    shots_on_target=_int(_stat(st, "shots_on_target", side)),
                    corners=_int(_stat(st, "corner_kicks", side)), fouls=_int(_stat(st, "fouls", side)),
                    possession_pct=pos))
        tl = (b.get("timeline") or {}).get("events") or []
        for e in tl:
            typ = EVENT_TYPES.get(e.get("type"))
            if typ is None or e.get("period") == "penalties" or e.get("minute") is None:
                continue
            tid = (e.get("team") or {}).get("id")
            team = home if tid == hid else away
            if typ == "corner":                       # zrodlo: druzyna, ktora rozny oddala
                team = away if team == home else home
            out.append(MatchEvent(**base, source_key=f"{m['id']}:ev:{e.get('sequence')}", available_at=post,
                                  minute=int(e["minute"]), extra_minute=int(e.get("extra_time") or 0) or None,
                                  type=typ, team=team, player=(e.get("player") or {}).get("name")))
        lu = b.get("lineups")
        if lu:
            lu_at = min(ko - LINEUP_LEAD, fetched)
            for side, team in (("home", home), ("away", away)):
                t = lu.get(side) or {}
                for status, key in (("start", "starting_xi"), ("lawka", "substitutes")):
                    for p in t.get(key) or []:
                        out.append(LineupEntry(**base, source_key=f"{m['id']}:lu:{side}:{p.get('id')}",
                                               available_at=lu_at, available_at_estimated=True, team=team,
                                               player=p.get("name") or p.get("id"), status=status,
                                               position=p.get("position")))
        od = b.get("odds") or {}
        for bk in od.get("bookmakers") or []:
            book = BOOK_SLUG.get(bk.get("bookmaker"), str(bk.get("bookmaker", "")).lower().replace(" ", "_"))
            for market, sel, line, q in _quotes(bk.get("markets") or {}):
                for field, kind in (("last_seen", "close"), ("opening", "bench")):
                    price = _num(q.get(field))
                    if price is None or price <= 1:
                        continue
                    out.append(OddsQuote(**base, source_key=f"{m['id']}:{book}:{market}:{sel}:{field}",
                                         available_at=min(ko, fetched), available_at_estimated=True,
                                         bookmaker=book, market=market, selection=sel, line=line, price=price,
                                         kind=kind))
        return out


def _int(x):
    return int(x) if x is not None else None


def _quotes(mk: dict):
    """(rynek, selekcja, linia, {opening, last_seen}) w konwencji projektu."""
    mo = mk.get("match_odds") or {}
    for k, sel in (("home", "1"), ("draw", "X"), ("away", "2")):
        if k in mo:
            yield "1X2", sel, None, mo[k]
    bt = mk.get("btts") or {}
    for k in ("yes", "no"):
        if k in bt:
            yield "BTTS", k, None, bt[k]
    for key, prefix, sel_prefix in (("total_goals", "OU", ""), ("match_corners", "CORNERS", "")):
        for ln, d in (mk.get(key) or {}).items():
            line = _num(ln)
            if line is None or not isinstance(d, dict):
                continue
            for side in ("over", "under"):
                if isinstance(d.get(side), dict):
                    yield f"{prefix}{line:g}", f"{side}{line:g}", line, d[side]
