"""Probki odpowiedzi zrodel (format prawdziwy, wartosci FIKCYJNE) dla kazdego adaptera z rejestru.
Dodajesz adapter = dodajesz tu probki. Brak wpisu oblewa test_available_at (bez cichego pomijania)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from typer.ingest.core.adapter import RawPayload

FIX = Path(__file__).parent / "fixtures"
S = FIX / "samples"


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s)


SAMPLES: dict[str, list[dict]] = {
    "football_data_uk": [
        dict(file=FIX / "fduk_E0_sample.csv", fetched_at="2024-08-25T00:00:00+00:00", ctx=dict(league="E0", kind="main")),
        dict(file=S / "fduk_fixtures.csv", fetched_at="2024-08-29T10:00:00+00:00", ctx=dict(kind="fixtures")),
    ],
    "xgabora": [dict(file=S / "xgabora.csv", fetched_at="2026-09-05T08:00:00+00:00", ctx=dict(ref="test", since="2024-07-01"))],
    "the_odds_api": [
        dict(file=S / "odds_api.json", fetched_at="2024-08-17T13:55:00+00:00", ctx=dict(league="E0")),  # zamkniecie
        dict(file=S / "odds_api.json", fetched_at="2024-08-17T12:30:00+00:00", ctx=dict(league="E0")),  # w chwili typu
    ],
    "oddsrelay": [
        dict(file=S / "oddsrelay_raw.json", fetched_at="2026-10-16T12:00:00+00:00", ctx=dict(league="E0")),
        dict(file=S / "oddsrelay_closing.json", fetched_at="2026-10-17T06:00:00+00:00", ctx=dict(league="E0")),
    ],
    "api_football": [
        dict(file=S / "api_football_ft.json", fetched_at="2024-08-18T06:00:00+00:00", ctx={}),
        dict(file=S / "api_football_ns.json", fetched_at="2024-08-24T13:00:00+00:00", ctx={}),
    ],
    "open_meteo": [
        dict(file=S / "open_meteo_forecast.json", fetched_at="2026-11-05T10:00:00+00:00", ctx=dict(mode="forecast")),
        dict(file=S / "open_meteo_previous_runs.json", fetched_at="2026-11-05T10:00:00+00:00",
             ctx=dict(mode="previous_runs", previous_day=1)),
        dict(file=S / "open_meteo_archive.json", fetched_at="2026-11-05T10:00:00+00:00", ctx=dict(mode="archive")),
    ],
    "telegram": [dict(file=S / "telegram.json", fetched_at="2024-08-17T13:00:00+00:00", ctx={})],
    "betfair": [
        dict(file=S / "betfair_stream.jsonl", fetched_at="2026-11-05T10:00:00+00:00", ctx=dict(format="stream")),
        dict(file=S / "betfair_marketbook.json", fetched_at="2024-08-17T13:00:00+00:00", ctx=dict(format="rest")),
    ],
    "tennis_mcp": [
        dict(file=S / "mcp_matches.csv", fetched_at="2026-09-20T00:00:00+00:00", ctx=dict(kind="matches", tour="m")),
        dict(file=S / "mcp_overview.csv", fetched_at="2026-09-20T00:00:00+00:00", ctx=dict(kind="overview", tour="m")),
        dict(file=S / "mcp_points.csv", fetched_at="2026-09-20T00:00:00+00:00", ctx=dict(kind="points", tour="m")),
    ],
}


def payloads(name: str) -> list[RawPayload]:
    return [RawPayload(Path(s["file"]).name, Path(s["file"]).read_bytes(), _t(s["fetched_at"]), dict(s["ctx"]))
            for s in SAMPLES[name]]
