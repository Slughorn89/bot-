"""Budzet zapytan do platnych/limitowanych API (sekcja 5 skilla: licz budzet z gory).

The Odds API: limit miesieczny w kredytach, jedno zapytanie kosztuje rynki x regiony.
API-Football: limit dzienny zapytan, reset o polnocy UTC.
Ksiega w live/budget.json. Gdy API zwraca naglowki zuzycia, one sa zrodlem prawdy; inaczej
liczymy koszt sami. Zapytanie, ktore przekroczyloby budzet (z rezerwa), jest odrzucane z alarmem.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from typer import config


@dataclass
class Plan:
    league: str
    kind: str            # taken | close
    markets: list[str]
    cost: int
    kickoffs: list[str]


def _ledger_path() -> Path:
    return config.ROOT / "live" / "budget.json"


def _monthly(source: str) -> bool:
    return source == "the_odds_api" or "budzet_miesiac" in config.sources().get(source, {})


def _period(source: str, now: datetime) -> str:
    return now.strftime("%Y-%m") if _monthly(source) else now.strftime("%Y-%m-%d")


def _limit(source: str) -> tuple[int, float]:
    s = config.sources().get(source, {})
    lim = s.get("budzet_miesiac") if _monthly(source) else s.get("budzet_dzien")
    return int(lim or (500 if source == "the_odds_api" else 100)), float(s.get("rezerwa", 0.1))


class Ledger:
    def __init__(self, path: Path | None = None):
        self.path = path or _ledger_path()
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def used(self, source: str, now: datetime) -> int:
        d = self.data.get(source, {})
        return int(d.get("used", 0)) if d.get("period") == _period(source, now) else 0

    def remaining(self, source: str, now: datetime) -> int:
        lim, reserve = _limit(source)
        return int(lim * (1 - reserve)) - self.used(source, now)

    def can_spend(self, source: str, cost: int, now: datetime) -> bool:
        return cost <= self.remaining(source, now)

    def record(self, source: str, cost: int, now: datetime, headers: dict | None = None, note: str = "") -> None:
        per = _period(source, now)
        d = self.data.get(source, {})
        if d.get("period") != per:
            d = dict(period=per, used=0, calls=[])
        h = {k.lower(): v for k, v in (headers or {}).items()}
        if "x-requests-used" in h:  # The Odds API: naglowek = prawda
            d["used"] = int(float(h["x-requests-used"]))
        elif "x-tokens-remaining" in h:  # OddsRelay: tokeny pozostale w okresie
            lim, _ = _limit(source)
            d["used"] = max(int(d.get("used", 0)) + int(cost), lim - int(float(h["x-tokens-remaining"])))
        elif "x-ratelimit-requests-remaining" in h:  # API-Football
            lim, _ = _limit(source)
            d["used"] = lim - int(float(h["x-ratelimit-requests-remaining"]))
        else:
            d["used"] = int(d.get("used", 0)) + int(cost)
        d["calls"] = (d.get("calls", []) + [dict(ts=f"{now:%Y-%m-%d %H:%M}", koszt=cost, uwaga=note)])[-200:]
        self.data[source] = d
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1))


def odds_api_cost(markets: list[str], regions: list[str]) -> int:
    return max(1, len(markets)) * max(1, len(regions))


def plan_odds_snapshots(events: pd.DataFrame, now: datetime, done: set[tuple], ledger: Ledger,
                        lead_minutes: int = 90, close_window: int = 10) -> list[Plan]:
    """Ktore ligi odpytac teraz. Snapshot 'taken' raz na lige i dzien meczowy (przed pierwszym typem dnia,
    jedno zapytanie zwraca wszystkie mecze ligi), 'close' dla kazdej godziny startu w oknie zamkniecia.
    done: zbior juz wykonanych kluczy (liga, rodzaj, dzien albo godzina startu).
    Przy kurczacym sie budzecie najpierw odpada totals w 'taken', potem caly 'taken'; 'close' ma priorytet,
    bo bez zamkniecia nie ma CLV."""
    s = config.sources().get("the_odds_api", {})
    regions = s.get("regiony", ["eu"])
    m_close = s.get("rynki_zamkniecie", ["h2h", "totals"])
    m_taken = s.get("rynki_typ", ["h2h", "totals"])
    if events.empty:
        return []
    ko = pd.to_datetime(events["kickoff_utc"], utc=True)
    now_ts = pd.Timestamp(now)
    plans: list[Plan] = []
    for lg, g in events.assign(ko=ko).groupby("league"):
        cl = g[(g["ko"] > now_ts) & (g["ko"] <= now_ts + pd.Timedelta(minutes=close_window))]
        for slot, gg in cl.groupby("ko"):
            key = (lg, "close", str(slot))
            if key not in done:
                plans.append(Plan(lg, "close", m_close, odds_api_cost(m_close, regions), [str(slot)]))
        day = g[g["ko"].dt.date == now_ts.date()]
        if len(day):
            first = day["ko"].min()
            key = (lg, "taken", str(now_ts.date()))
            if key not in done and now_ts >= first - pd.Timedelta(minutes=lead_minutes + 15) and now_ts < first:
                plans.append(Plan(lg, "taken", m_taken, odds_api_cost(m_taken, regions),
                                  [str(x) for x in sorted(day["ko"].unique())]))
    # budzet: zamkniecia najpierw, potem typ (z degradacja rynkow)
    left = ledger.remaining("the_odds_api", now)
    out = []
    for p in sorted(plans, key=lambda p: p.kind != "close"):
        if p.cost <= left:
            out.append(p)
            left -= p.cost
        elif p.kind == "taken" and odds_api_cost(["h2h"], regions) <= left:
            out.append(Plan(p.league, "taken", ["h2h"], odds_api_cost(["h2h"], regions), p.kickoffs))
            left -= out[-1].cost
    return out


def estimate_month(slots_per_month: float, match_days_per_month: float, regions: int = 1,
                   close_markets: int = 2, taken_markets: int = 2) -> int:
    """Szacunek kredytow The Odds API na miesiac dla planu z plan_odds_snapshots."""
    return int(round(slots_per_month * close_markets * regions + match_days_per_month * taken_markets * regions))


def history_estimate(df: pd.DataFrame, season: str) -> pd.DataFrame:
    """Z danych historycznych: godziny startu i dni meczowe per liga i miesiac -> szacunek kredytow."""
    s = df[(df["season"] == season) & df["time_known"].astype(bool)]
    if s.empty:
        return pd.DataFrame()
    k = pd.to_datetime(s["kickoff_utc"], utc=True)
    s = s.assign(m=k.dt.strftime("%Y-%m"), slot=k.dt.strftime("%Y-%m-%d %H:%M"), d=k.dt.date)
    g = s.groupby("m").agg(sloty=("slot", lambda x: len(set(zip(s.loc[x.index, "league"], x)))),
                           dni=("d", lambda x: len(set(zip(s.loc[x.index, "league"], x)))))
    g["kredyty"] = [estimate_month(a, b) for a, b in zip(g["sloty"], g["dni"])]
    return g


def next_reset(source: str, now: datetime) -> datetime:
    if source == "the_odds_api":
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return (first + timedelta(days=32)).replace(day=1)
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
