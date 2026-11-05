"""Adapter: Tennis Abstract Match Charting Project (Jeff Sackmann), dane serwisowe i punktowe.

Licencja CC BY-NC-SA 4.0: wylacznie niekomercyjnie, z podaniem autora. Glowne repozytoria
tennis_atp / tennis_wta / tennis_slam_pointbypoint nie sa juz publiczne (sprawdzone 2026-11-05),
publiczny zostal tylko Match Charting Project (ok. 5 tys. recznie opisanych meczow, wybor meczow
nie jest losowy), wiec to dane do budowy modelu, nie pelne pokrycie do codziennego typowania.

available_at: data z pliku to w nowszych meczach dzien meczu, ale nie wiemy tego dla calej historii,
wiec przyjmujemy konserwatywny koniec turnieju: data + 14 dni (Wielki Szlem) albo + 7 dni, szacunek.
"""
from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from typer import config
from typer.ingest.core.adapter import Adapter, RawPayload, register
from typer.ingest.core.records import TennisMatch, TennisPoint, TennisServeStats
from typer.ingest.schema import ContractError

log = logging.getLogger("typer.ingest.tennis")

SLAMS = ("australian open", "roland garros", "french open", "wimbledon", "us open")
REQUIRED = {"matches": {"match_id", "Player 1", "Player 2", "Date", "Tournament"},
            "overview": {"match_id", "player", "set", "serve_pts", "aces", "dfs", "first_in", "first_won",
                         "second_in", "second_won", "bk_pts", "bp_saved", "return_pts", "return_pts_won"},
            "points": {"match_id", "Pt", "Set1", "Set2", "Gm1", "Gm2", "Pts", "Svr", "PtWinner"}}


def _date_from_id(match_id: str) -> date:
    return datetime.strptime(match_id[:8], "%Y%m%d").date()


def _lag(match_id: str, tournament: str | None = None) -> timedelta:
    """Konserwatywny koniec turnieju: Wielki Szlem 14 dni, reszta 7 dni od daty z pliku."""
    parts = match_id.split("-")
    name = tournament if tournament else (parts[2] if len(parts) > 2 else "")
    name = name.replace("_", " ").lower()
    return timedelta(days=14 if any(s in name for s in SLAMS) else 7)


RENAME = {"Player 1": "player1", "Player 2": "player2", "Pl 1 hand": "hand1", "Pl 2 hand": "hand2",
          "Best of": "best_of", "Final TB?": "final_tb", "Charted by": "charted_by"}


@register
class TennisMCP(Adapter):
    name = "tennis_mcp"
    license = "CC BY-NC-SA 4.0, Tennis Abstract Match Charting Project (Jeff Sackmann)"
    non_commercial = True
    record_types = (TennisMatch, TennisServeStats, TennisPoint)

    def __init__(self, client=None):
        super().__init__(client)
        self.skipped: list[str] = []  # uszkodzone/niepelne wiersze pominiete jawnie (z logiem)

    def _drop_incomplete(self, df: pd.DataFrame, cols: list[str], name: str) -> pd.DataFrame:
        num = df[cols].apply(pd.to_numeric, errors="coerce")
        bad = num.isna().any(axis=1)
        if bad.any():
            self.skipped += list(df.loc[bad, "match_id"].astype(str))
            log.warning("MCP %s: pominieto %d niepelnych wierszy (puste/nieliczbowe %s)", name, int(bad.sum()),
                        ", ".join(cols))
        out = df[~bad].copy()
        out[cols] = num[~bad].astype(int)
        return out

    def fetch(self, tour: str = "m", kinds: tuple[str, ...] = ("matches", "overview"),
              points_decade: str = "2020s") -> list[RawPayload]:
        src = config.sources()["tennis_mcp"]
        files = {"matches": f"charting-{tour}-matches.csv", "overview": f"charting-{tour}-stats-Overview.csv",
                 "points": f"charting-{tour}-points-{points_decade}.csv"}
        out = []
        for k in kinds:
            url = src["url"].format(ref=src["ref"], file=files[k])
            r = self.client.get(url, f"{src['ref'][:12]}_{files[k]}", max_age_hours=None)  # przypiety commit
            out.append(RawPayload(files[k], r.content, r.fetched_at, dict(kind=k, tour=tour)))
        return out

    def parse(self, payload: RawPayload) -> list:
        kind, tour = payload.ctx["kind"], payload.ctx.get("tour", "m")
        df = pd.read_csv(io.BytesIO(payload.content), low_memory=False, encoding_errors="replace")
        missing = REQUIRED[kind] - set(df.columns)
        if missing:
            raise ContractError(f"MCP {kind}: brak kolumn {sorted(missing)}")
        fetched = payload.fetched_at
        out = []
        base = dict(source=self.name, license=self.license, fetched_at=fetched, available_at_estimated=True)
        if kind == "matches":
            df = df.rename(columns=RENAME)
            dates = pd.to_datetime(df["Date"].astype(str).str.replace(r"\.0$", "", regex=True), format="%Y%m%d",
                                   errors="coerce")
            bad = df[dates.isna()]
            if len(bad):  # dane crowdsourcingowe: wiersz z przesunietymi kolumnami pomijamy jawnie
                self.skipped += list(bad["match_id"].astype(str))
                log.warning("MCP %s: pominieto %d uszkodzonych wierszy (zla data): %s", payload.name, len(bad),
                            ", ".join(self.skipped[:5]))
            df = df[dates.notna()].assign(mdate=dates[dates.notna()].dt.date)
            for r in df.itertuples(index=False):
                d = r.mdate
                start = datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
                at = min(start + _lag(r.match_id, r.Tournament), fetched)
                if at < start:
                    continue
                g = lambda c: (None if pd.isna(getattr(r, c, None)) else getattr(r, c))
                bo = g("best_of")
                out.append(TennisMatch(**base, source_key=f"mcp:match:{r.match_id}", available_at=at,
                                       match_id=r.match_id, tour="atp" if tour == "m" else "wta", match_date=d,
                                       tournament=r.Tournament, round=g("Round"), surface=g("Surface"),
                                       best_of=int(float(bo)) if bo is not None and str(bo).replace(".0", "").isdigit()
                                       else None, player1=r.player1, player2=r.player2,
                                       hand1=g("hand1"), hand2=g("hand2")))
        elif kind == "overview":
            tot = df[df["set"].astype(str) == "Total"]
            tot = self._drop_incomplete(tot, ["serve_pts", "aces", "dfs", "first_in", "first_won", "second_in",
                                              "second_won", "bk_pts", "bp_saved", "return_pts", "return_pts_won"],
                                        payload.name)
            for r in tot.itertuples(index=False):
                d = _date_from_id(r.match_id)
                start = datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
                at = min(start + _lag(r.match_id), fetched)
                if at < start + timedelta(days=1):
                    continue
                out.append(TennisServeStats(
                    **base, source_key=f"mcp:serve:{r.match_id}:{r.player}", available_at=at, match_id=r.match_id,
                    match_date=d, player=r.player, serve_pts=int(r.serve_pts), aces=int(r.aces), dfs=int(r.dfs),
                    first_in=int(r.first_in), first_won=int(r.first_won), second_in=int(r.second_in),
                    second_won=int(r.second_won), bk_pts=int(r.bk_pts), bp_saved=int(r.bp_saved),
                    return_pts=int(r.return_pts), return_pts_won=int(r.return_pts_won)))
        else:  # points
            limit = payload.ctx.get("limit")
            part = df.head(limit) if limit else df
            part = self._drop_incomplete(part, ["Pt", "Set1", "Set2", "Gm1", "Gm2", "Svr", "PtWinner"], payload.name)
            part = part[part["Svr"].isin([1, 2]) & part["PtWinner"].isin([1, 2])]
            for r in part.itertuples(index=False):
                d = _date_from_id(r.match_id)
                start = datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
                at = min(start + _lag(r.match_id), fetched)
                if at < start + timedelta(days=1):
                    continue
                tb = getattr(r, "TbSet", None)
                out.append(TennisPoint(
                    **base, source_key=f"mcp:pt:{r.match_id}:{int(r.Pt)}", available_at=at, match_id=r.match_id,
                    match_date=d, pt=int(r.Pt), set1=int(r.Set1), set2=int(r.Set2), gm1=int(r.Gm1), gm2=int(r.Gm2),
                    pts=str(r.Pts), tiebreak_set=None if pd.isna(tb) else str(tb).lower() in ("1", "true"),
                    server=int(r.Svr), pt_winner=int(r.PtWinner)))
        return out
