"""Uzupelnienie Ekstraklasy z pliku "nowe ligi" football-data.co.uk: tylko mecze po kopii xgabora, zamkniecia
w close_* (Pinnacle, a gdy pusty: gielda Betfair), kurs "wziety" pusty (bez wycieku)."""
import numpy as np
import pandas as pd

CSV = (b"\xef\xbb\xbfCountry,League,Season,Date,Time,Home,Away,HG,AG,Res,PSCH,PSCD,PSCA,MaxCH,MaxCD,MaxCA,"
       b"AvgCH,AvgCD,AvgCA,BFECH,BFECD,BFECA,B365CH,B365CD,B365CA\n"
       b"Poland,Ekstraklasa,2024/2025,05/10/2024,17:30,Legia,Rakow,1,1,D,2.1,3.4,3.6,,,,2.0,3.3,3.4,,,,,,\n"
       b"Poland,Ekstraklasa,2024/2025,20/10/2024,17:30,Lech Poznan,Legia,2,0,H,1.9,3.6,4.2,,,,1.8,3.5,4.0,,,,,,\n"
       b"Poland,Ekstraklasa,2026/2027,08/11/2026,16:30,Legia,Rakow,2,4,A,,,,2.05,3.65,3.45,2.0,3.44,3.31,"
       b"2.14,3.7,3.65,1.95,3.5,3.4\n")


def test_extend_only_after_last_date_and_no_taken_odds(monkeypatch):
    from typer.ingest import footballdata_uk as fduk
    from typer.ingest import schema
    from typer.pipeline import data
    monkeypatch.setattr(fduk, "fetch", lambda *a, **k: CSV)
    base = fduk.parse(CSV, "POL", kind="new").iloc[:1].copy()        # "kopia xgabora" konczy sie 2024-10-05
    base["odds_h"] = 2.2
    out = data.extend_new_leagues(base[schema.COLUMNS])
    pol = out[out["league"] == "POL"].sort_values("date")
    assert len(pol) == 3 and pol["event_id"].is_unique
    assert pol["odds_h"].iloc[0] == 2.2                               # stary wiersz bez zmian
    assert pol["odds_h"].iloc[1:].isna().all()                        # zamkniecie nie udaje kursu "wzietego"
    assert pol["close_h"].iloc[1] == 1.9                              # Pinnacle
    assert pol["close_h"].iloc[2] == 2.14                             # Pinnacle pusty: Betfair
    assert pol["bench_h"].iloc[2] == 2.0 and np.isnan(pol["hs"].iloc[2])
