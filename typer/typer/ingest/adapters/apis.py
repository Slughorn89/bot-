"""Adaptery API: The Odds API ({{api_kursowe}}) i API-Football ({{api_statystyki}}).

The Odds API: snapshot kursow; available_at = chwila snapshotu. Mecz trwajacy pomijamy.
API-Football (/fixtures?id= zwraca tez events, lineups, statistics, players):
  * dane pomeczowe (wynik, statystyki druzyn i zawodnikow, zdarzenia: karne, kartki) tylko dla meczow
    zakonczonych (FT/AET/PEN); available_at = min(start + 2h15, fetched_at),
  * sedzia: pobrany przed startem = fetched_at; pobrany po fakcie = min(start - 24h, fetched_at), szacunek,
  * sklady i kontuzje: pobrane przed startem = fetched_at; po fakcie = min(start - 60 min, fetched_at), szacunek.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from typer import config
from typer.ingest.core.adapter import Adapter, RawPayload, register
from typer.ingest.core.records import (POST_MATCH_LAG, LineupEntry, MatchEvent, MatchResult, OddsQuote,
                                       PlayerMatchStats, RefereeAssignment, TeamMatchStats)
from typer.ingest.schema import ContractError

CLOSE_WINDOW = timedelta(minutes=10)
FINISHED = {"FT", "AET", "PEN"}
LINEUP_LEAD = timedelta(minutes=60)
REFEREE_LEAD = timedelta(hours=24)


@register
class TheOddsAPI(Adapter):
    name = "the_odds_api"
    license = "The Odds API: komercyjna, plan darmowy 500 kredytow/mies."
    record_types = (OddsQuote,)

    def fetch(self, leagues: list[str] | None = None, markets: str = "h2h,totals") -> list[RawPayload]:
        from typer.ingest import odds_api
        out = []
        for lg in leagues or list(config.leagues()):
            sport = config.leagues()[lg].get("odds_api")
            meta: dict = {}
            raw = odds_api.download(sport, markets=markets, meta_out=meta)
            out.append(RawPayload(f"{sport}.json", raw, meta.get("fetched_at") or datetime.now(timezone.utc),
                                  dict(league=lg)))
        return out

    def parse(self, payload: RawPayload) -> list:
        data = json.loads(payload.content)
        if not isinstance(data, list):
            raise ContractError(f"The Odds API: oczekiwana lista meczow: {str(data)[:200]}")
        snap = payload.fetched_at
        out = []
        for ev in data:
            missing = {"id", "home_team", "away_team", "commence_time", "bookmakers"} - set(ev)
            if missing:
                raise ContractError(f"The Odds API: brak pol {sorted(missing)}")
            ko = pd.Timestamp(ev["commence_time"]).tz_convert("UTC").to_pydatetime()
            if ko <= snap:
                continue  # mecz trwa albo sie skonczyl: to nie kurs przedmeczowy
            kind = "close" if ko - snap <= CLOSE_WINDOW else "taken"
            home, away = ev["home_team"], ev["away_team"]
            for bk in ev["bookmakers"]:
                for m in bk.get("markets", []):
                    for o in m.get("outcomes", []):
                        if m["key"] == "h2h":
                            market, line = "1X2", None
                            sel = "1" if o["name"] == home else "2" if o["name"] == away else "X"
                        elif m["key"] == "totals" and o.get("point") is not None:
                            line = float(o["point"])
                            market, sel = f"OU{line:g}", f"{o['name'].lower()}{line:g}"
                        else:
                            continue
                        out.append(OddsQuote(
                            source=self.name, license=self.license, league=payload.ctx["league"],
                            kickoff_utc=ko, home=home, away=away,
                            source_key=f"{ev['id']}:{bk['key']}:{market}:{sel}:{snap:%Y%m%dT%H%M%S}",
                            available_at=snap, fetched_at=snap, bookmaker=bk["key"], market=market,
                            selection=sel, line=line, price=float(o["price"]), kind=kind))
        return out


def _referee_name(s: str | None) -> str | None:
    if not s:
        return None
    return s.split(",")[0].strip() or None  # "M. Oliver, England" -> "M. Oliver"


def _stat(items: list[dict], *names) -> float | None:
    for it in items:
        if it.get("type") in names and it.get("value") not in (None, ""):
            v = it["value"]
            if isinstance(v, str):
                v = v.strip().rstrip("%")
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    return None


@register
class APIFootball(Adapter):
    name = "api_football"
    license = "API-Sports: komercyjna, plan darmowy 100 zapytan/dzien"
    record_types = (MatchResult, TeamMatchStats, PlayerMatchStats, MatchEvent, RefereeAssignment, LineupEntry)

    def fetch(self, fixture_ids: list[int] | None = None, league: str | None = None, season: int | None = None,
              date: str | None = None) -> list[RawPayload]:
        from typer.ingest import api_football as af
        out = []
        ids = list(fixture_ids or [])
        if league and season and date:
            lid = config.sources()["api_football"]["ligi"][league]
            raw = af.download("/fixtures", dict(league=lid, season=season, date=date), max_age_hours=6, stamp=date)
            ids += [f["fixture"]["id"] for f in json.loads(raw).get("response", [])
                    if f["fixture"]["status"]["short"] in FINISHED]
        for fid in ids:
            meta: dict = {}
            # mecz zakonczony sie nie zmienia: cache bezterminowy oszczedza dzienny limit
            raw = af.download("/fixtures", dict(id=int(fid)), max_age_hours=None, stamp="full", meta_out=meta)
            out.append(RawPayload(f"fixture_{fid}.json", raw, meta.get("fetched_at") or datetime.now(timezone.utc)))
        return out

    def _league_code(self, league_id: int) -> str:
        rev = {v: k for k, v in (config.sources().get("api_football", {}).get("ligi") or {}).items()}
        return rev.get(league_id, f"AF{league_id}")

    def parse(self, payload: RawPayload) -> list:
        body = json.loads(payload.content)
        if "response" not in body:
            raise ContractError("API-Football: brak pola 'response'")
        out = []
        for f in body["response"]:
            missing = {"fixture", "league", "teams"} - set(f)
            if missing:
                raise ContractError(f"API-Football: brak pol {sorted(missing)}")
            out += self._fixture_records(f, payload.fetched_at)
        return out

    def _fixture_records(self, f: dict, fetched: datetime) -> list:
        fx = f["fixture"]
        ko = pd.Timestamp(fx["date"]).tz_convert("UTC").to_pydatetime()
        home, away = f["teams"]["home"]["name"], f["teams"]["away"]["name"]
        fid = fx["id"]
        ref = dict(source=self.name, license=self.license, league=self._league_code(f["league"]["id"]),
                   kickoff_utc=ko, home=home, away=away, fetched_at=fetched)
        out = []
        referee = _referee_name(fx.get("referee"))
        if referee:
            before = fetched <= ko
            out.append(RefereeAssignment(**ref, source_key=f"af:{fid}:referee", referee=referee,
                                         available_at=fetched if before else min(ko - REFEREE_LEAD, fetched),
                                         available_at_estimated=not before))
        lu_before = fetched <= ko
        lu_at = fetched if lu_before else min(ko - LINEUP_LEAD, fetched)
        for t in f.get("lineups") or []:
            for group, status in (("startXI", "start"), ("substitutes", "lawka")):
                for p in t.get(group) or []:
                    pl = p["player"]
                    out.append(LineupEntry(**ref, source_key=f"af:{fid}:lineup:{t['team']['name']}:{pl.get('id') or pl['name']}",
                                           available_at=lu_at, available_at_estimated=not lu_before,
                                           team=t["team"]["name"], player=pl["name"], status=status,
                                           position=pl.get("pos")))
        if fx.get("status", {}).get("short") not in FINISHED:
            return out  # bez danych pomeczowych z meczu, ktory sie nie skonczyl
        post = min(ko + POST_MATCH_LAG, fetched)
        g, ht = f.get("goals") or {}, (f.get("score") or {}).get("halftime") or {}
        if g.get("home") is not None and g.get("away") is not None:
            out.append(MatchResult(**ref, source_key=f"af:{fid}:result", available_at=post,
                                   fthg=g["home"], ftag=g["away"], hthg=ht.get("home"), htag=ht.get("away")))
        for st in f.get("statistics") or []:
            team = st["team"]["name"]
            items = st.get("statistics") or []
            side = "home" if team == home else "away"
            out.append(TeamMatchStats(
                **ref, source_key=f"af:{fid}:stats:{side}", available_at=post, team=team, side=side,
                xg=_stat(items, "expected_goals"), shots=_int(_stat(items, "Total Shots")),
                shots_on_target=_int(_stat(items, "Shots on Goal")), corners=_int(_stat(items, "Corner Kicks")),
                fouls=_int(_stat(items, "Fouls")), yellow=_int(_stat(items, "Yellow Cards")),
                red=_int(_stat(items, "Red Cards")), possession_pct=_stat(items, "Ball Possession")))
        for tp in f.get("players") or []:
            team = tp["team"]["name"]
            for p in tp.get("players") or []:
                s = (p.get("statistics") or [{}])[0]
                gm, sh, gl = s.get("games") or {}, s.get("shots") or {}, s.get("goals") or {}
                fo, cd = s.get("fouls") or {}, s.get("cards") or {}
                out.append(PlayerMatchStats(
                    **ref, source_key=f"af:{fid}:player:{p['player'].get('id') or p['player']['name']}",
                    available_at=post, team=team, player=p["player"]["name"],
                    player_ref=str(p["player"].get("id")) if p["player"].get("id") else None,
                    position=gm.get("position"), minutes=gm.get("minutes"), goals=gl.get("total"),
                    assists=gl.get("assists"), shots=sh.get("total"), shots_on_target=sh.get("on"),
                    fouls_committed=fo.get("committed"), fouls_drawn=fo.get("drawn"),
                    yellow=cd.get("yellow"), red=cd.get("red")))
        for i, e in enumerate(f.get("events") or []):
            typ = _event_type(e.get("type"), e.get("detail"))
            if typ is None:
                continue
            tm = e.get("time") or {}
            out.append(MatchEvent(**ref, source_key=f"af:{fid}:event:{i}", available_at=post,
                                  minute=int(tm.get("elapsed") or 0), extra_minute=tm.get("extra"), type=typ,
                                  team=(e.get("team") or {}).get("name") or "", player=(e.get("player") or {}).get("name")))
        return out

    def parse_injuries(self, payload: RawPayload, kickoffs: dict[int, tuple]) -> list:
        """/injuries: kickoffs = {fixture_id: (liga, start, gospodarz, gosc)} z terminarza."""
        out = []
        for x in json.loads(payload.content).get("response", []):
            fid = x["fixture"]["id"]
            if fid not in kickoffs:
                continue
            lg, ko, home, away = kickoffs[fid]
            before = payload.fetched_at <= ko
            reason = x["player"].get("reason") or ""
            typ = (x["player"].get("type") or "").lower()
            status = "zawieszenie" if "suspen" in reason.lower() else (
                "watpliwy" if "question" in typ or "doubt" in typ else "nieobecny")
            out.append(LineupEntry(source=self.name, license=self.license, league=lg, kickoff_utc=ko, home=home,
                                   away=away, fetched_at=payload.fetched_at,
                                   source_key=f"af:{fid}:injury:{x['player'].get('id') or x['player']['name']}",
                                   available_at=payload.fetched_at if before else min(ko - LINEUP_LEAD, payload.fetched_at),
                                   available_at_estimated=not before, team=x["team"]["name"],
                                   player=x["player"]["name"], status=status, reason=reason or None))
        return out


def _int(v):
    return None if v is None else int(v)


def _event_type(t: str | None, d: str | None) -> str | None:
    t, d = (t or "").lower(), (d or "").lower()
    if t == "goal":
        return {"own goal": "own_goal", "penalty": "penalty_scored", "missed penalty": "penalty_missed"}.get(d, "goal")
    if t == "card":
        if "second" in d:
            return "second_yellow"
        return "red" if "red" in d else "yellow" if "yellow" in d else None
    return None
