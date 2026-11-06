"""Pobranie sezonu z TheStatsAPI do lokalnego cache (raw/thestatsapi, poza repo) i ramek w data/ (poza repo).
Uzycie: python backtest/statsapi/fetch_season.py E0 24/25 [timeline,stats,odds]
Paczka meczu bez osobnego zapytania o mecz (wynik i druzyny sa w liscie) i bez skladow: przebieg, statystyki, kursy."""
import json
import pickle
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from typer import config  # noqa: E402
from typer.ingest import thestatsapi as api  # noqa: E402
from typer.ingest.adapters.thestatsapi import TheStatsAPI  # noqa: E402
from typer.ingest.core.adapter import RawPayload  # noqa: E402

lg, year = sys.argv[1], sys.argv[2]
PARTS = tuple("/" + p for p in (sys.argv[3] if len(sys.argv) > 3 else "timeline,stats,odds").split(","))
cid = config.sources()["thestatsapi"]["ligi"][lg]
seasons = api.get(f"/football/competitions/{cid}/seasons", None, f"seasons_{cid}.json").get("data", [])
sid = next(s["id"] for s in seasons if s.get("year") == year)
ms = api.matches(cid, sid)
print(f"{lg} {year}: {len(ms)} meczow", flush=True)
recs, ad = [], TheStatsAPI()
for i, m in enumerate(ms):
    b = json.loads(api.match_bundle(m["id"], parts=PARTS))
    m = dict(m)
    m.setdefault("competition_id", cid)
    b["match"] = m
    recs += ad.parse(RawPayload(f"{m['id']}.json", json.dumps(b).encode(), datetime.now(timezone.utc), dict(league=lg)))
    if i % 50 == 0:
        print(i, flush=True)
out = config.DATA_DIR / f"thestatsapi_{lg}_{year.replace('/', '')}.pkl"
with open(out, "wb") as f:
    pickle.dump([r.model_dump() | {"_type": type(r).__name__} for r in recs], f)
print("zapisano", out, len(recs), flush=True)
