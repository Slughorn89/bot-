"""Adaptery historii pilkarskiej: football-data.co.uk (docelowe, z zamknieciami Pinnacle i sedziami)
i kopia xgabora na GitHubie (dostepna w tej sesji). Oba zwracaja rekordy z available_at."""
from __future__ import annotations

from typer import config
from typer.ingest import footballdata_uk, xgabora
from typer.ingest.adapters._football import frame_to_records
from typer.ingest.core.adapter import Adapter, RawPayload, register
from typer.ingest.core.records import MatchResult, OddsQuote, RefereeAssignment, TeamMatchStats


@register
class FootballDataUK(Adapter):
    name = "football_data_uk"
    license = "football-data.co.uk: darmowe, z podaniem zrodla"
    record_types = (MatchResult, OddsQuote, TeamMatchStats, RefereeAssignment)

    def fetch(self, seasons: list[str] | None = None, leagues: dict | None = None, fixtures: bool = False
              ) -> list[RawPayload]:
        src = config.sources()["football_data_uk"]
        leagues = leagues or config.leagues()
        out = []
        if fixtures:
            r = self.client.get(src["url_terminarz"], "fixtures.csv", max_age_hours=3)
            return [RawPayload("fixtures.csv", r.content, r.fetched_at, dict(kind="fixtures"))]
        for lg, meta in leagues.items():
            f = meta.get("fduk", {})
            if f.get("kind") == "new":
                r = self.client.get(src["url_nowe_ligi"].format(code=f["code"]), f"new_{f['code']}.csv")
                out.append(RawPayload(f"new_{f['code']}.csv", r.content, r.fetched_at, dict(league=lg, kind="new")))
                continue
            for s in seasons or []:
                code = footballdata_uk.season_code(s)
                r = self.client.get(src["url_sezon"].format(season=code, code=f["code"]), f"{code}_{f['code']}.csv")
                out.append(RawPayload(f"{code}_{f['code']}.csv", r.content, r.fetched_at,
                                      dict(league=lg, kind="main")))
        return out

    def parse(self, payload: RawPayload) -> list:
        ctx = payload.ctx
        if ctx.get("kind") == "fixtures":
            import io
            import pandas as pd
            df = pd.read_csv(io.BytesIO(payload.content), encoding="utf-8-sig")
            recs = []
            for lg, meta in config.leagues().items():
                part = df[df.get("Div", pd.Series(dtype=str)) == meta.get("fduk", {}).get("code")]
                if len(part):
                    fr = footballdata_uk.parse(part.to_csv(index=False).encode(), lg, kind="main",
                                               allow_unplayed=True, extended=True)
                    recs += frame_to_records(fr, self.name, payload.fetched_at, self.license)
            return recs
        df = footballdata_uk.parse(payload.content, ctx["league"], kind=ctx.get("kind", "main"), extended=True)
        return frame_to_records(df, self.name, payload.fetched_at, self.license)


@register
class Xgabora(Adapter):
    name = "xgabora"
    license = "MIT (repozytorium); dane football-data.co.uk i ClubElo, z podaniem zrodla"
    record_types = (MatchResult, OddsQuote, TeamMatchStats)

    def fetch(self, ref: str | None = None) -> list[RawPayload]:
        src = config.sources()["xgabora"]
        ref = ref or src["ref"]
        r = self.client.get(src["url"].format(ref=ref), f"Matches_{ref[:12]}.csv",
                            max_age_hours=None if len(ref) == 40 else 24)
        return [RawPayload(f"Matches_{ref[:12]}.csv", r.content, r.fetched_at, dict(ref=ref))]

    def parse(self, payload: RawPayload) -> list:
        since = payload.ctx.get("since") or config.gates()["split"]["data_od"]
        df = xgabora.parse(payload.content, config.leagues(), since=since, ref=payload.ctx.get("ref", ""),
                           extended=True)
        return frame_to_records(df, self.name, payload.fetched_at, self.license)
