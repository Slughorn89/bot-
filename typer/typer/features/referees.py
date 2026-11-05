"""Historia sedziow liczona "as of": kartki, faule i karne na mecz z meczow, ktore byly juz dostepne.

Nie przechowujemy gotowych srednich "na dzis" (to klasyczny wyciek: tabela "na dzis" zamiast
"na dzien meczu"). Kazde zapytanie liczy srednie wylacznie z rekordow z available_at <= as_of.
Wejscie: rekordy RefereeAssignment, TeamMatchStats i MatchEvent (z adapterow modulu 1).
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from typer.ingest.core.records import MatchEvent, RefereeAssignment, TeamMatchStats


def _key(r) -> tuple:
    return (r.league, pd.Timestamp(r.kickoff_utc).floor("min"), r.home, r.away)


def referee_history(assignments: list[RefereeAssignment], stats: list[TeamMatchStats],
                    events: list[MatchEvent], as_of: datetime, min_matches: int = 1) -> pd.DataFrame:
    """Wiersz na sedziego: mecze, zolte/czerwone/faule/karne na mecz. Tylko mecze rozegrane przed as_of
    i tylko dane z available_at <= as_of (obsada, statystyki i zdarzenia osobno)."""
    as_of = pd.Timestamp(as_of)
    assign = {}
    for a in assignments:
        if a.role == "main" and pd.Timestamp(a.available_at) <= as_of and pd.Timestamp(a.kickoff_utc) < as_of:
            assign[_key(a)] = a.referee
    per_match: dict[tuple, dict] = {}
    for s in stats:
        k = _key(s)
        if k not in assign or pd.Timestamp(s.available_at) > as_of:
            continue
        m = per_match.setdefault(k, dict(yellow=0.0, red=0.0, fouls=0.0, penalties=0.0, sides=0))
        m["yellow"] += s.yellow or 0
        m["red"] += s.red or 0
        m["fouls"] += s.fouls or 0
        m["sides"] += 1
    for e in events:
        k = _key(e)
        if k in per_match and pd.Timestamp(e.available_at) <= as_of and e.type in ("penalty_scored", "penalty_missed"):
            per_match[k]["penalties"] += 1
    rows = [dict(referee=assign[k], **v) for k, v in per_match.items() if v["sides"] == 2]
    if not rows:
        return pd.DataFrame(columns=["referee", "mecze", "zolte_na_mecz", "czerwone_na_mecz", "faule_na_mecz",
                                     "karne_na_mecz"])
    df = pd.DataFrame(rows)
    g = df.groupby("referee").agg(mecze=("sides", "size"), zolte_na_mecz=("yellow", "mean"),
                                  czerwone_na_mecz=("red", "mean"), faule_na_mecz=("fouls", "mean"),
                                  karne_na_mecz=("penalties", "mean")).reset_index()
    return g[g["mecze"] >= min_matches].sort_values("mecze", ascending=False).reset_index(drop=True)
