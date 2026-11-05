"""Kontrakt zrodel (sekcja 12.1): pole zniklo = test czerwony; to samo pobranie dwa razy = te same wiersze."""
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from typer import config
from typer.ingest import footballdata_uk, odds_api, schema, xgabora

FIX = Path(__file__).parent / "fixtures"
XG_HEADER = ("Division,MatchDate,MatchTime,HomeTeam,AwayTeam,FTHome,FTAway,HTHome,HTAway,HomeShots,AwayShots,"
             "HomeTarget,AwayTarget,HomeRed,AwayRed,OddHome,OddDraw,OddAway,MaxHome,MaxDraw,MaxAway,Over25,Under25,"
             "MaxOver25,MaxUnder25,HandiSize,HandiHome,HandiAway\n")
XG_ROWS = ("E0,2024-08-17,15:00:00,Arsenal,Wolves,2,0,1,0,18,9,6,3,0,0,1.25,6.5,10,1.28,7,11.5,1.44,2.75,1.48,2.9,"
           "-1.75,1.95,1.95\n"
           "E0,2024-08-24,15:00:00,Wolves,Chelsea,2,6,1,2,9,15,3,9,0,0,4.0,3.8,1.85,4.2,4.0,1.9,1.6,2.3,1.65,2.4,"
           "0.5,1.9,2.0\n")


def test_xgabora_kontrakt_i_idempotencja():
    raw = (XG_HEADER + XG_ROWS).encode()
    lg = {"E0": config.leagues()["E0"]}
    a, b = xgabora.parse(raw, lg), xgabora.parse(raw, lg)
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == 2 and str(pd.to_datetime(a["kickoff_utc"]).dt.tz) == "UTC"
    broken = pd.read_csv(io.BytesIO(raw)).drop(columns=["FTHome"]).to_csv(index=False).encode()
    with pytest.raises(schema.ContractError, match="FTHome"):
        xgabora.parse(broken, lg)


def test_footballdata_uk_pole_zniklo():
    raw = (FIX / "fduk_E0_sample.csv").read_bytes()
    pd.testing.assert_frame_equal(footballdata_uk.parse(raw, "E0"), footballdata_uk.parse(raw, "E0"))
    broken = pd.read_csv(io.BytesIO(raw)).drop(columns=["FTHG"]).to_csv(index=False).encode()
    with pytest.raises(schema.ContractError, match="fthg"):
        footballdata_uk.parse(broken, "E0")


def test_odds_api_pole_zniklo_albo_zly_format():
    raw = json.loads((FIX / "odds_api_sample.json").read_text())
    now = datetime(2018, 9, 8, 14, 55, tzinfo=timezone.utc)
    del raw[0]["home_team"]
    with pytest.raises(schema.ContractError, match="home_team"):
        odds_api.parse(json.dumps(raw).encode(), "E0", now)
    with pytest.raises(schema.ContractError, match="lista"):
        odds_api.parse(b'{"message": "Usage quota has been reached"}', "E0", now)
