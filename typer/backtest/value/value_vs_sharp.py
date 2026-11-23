"""Wpis 36: przewaga bez lepszego modelu. Zaklad u miekkiego bukmachera (Bet365), gdy jego kurs SPRZED meczu
przebija uczciwy kurs Pinnacle z TEJ SAMEJ chwili (football-data.co.uk zbiera oba w jednym momencie).
Ocena: CLV wzgledem zamkniecia Pinnacle bez marzy (glowny KPI), ROI pomocniczo, oba z bootstrapowym CI.
Ustalone przed uruchomieniem: prog 2%, rynki 1X2 i O/U 2.5, marza Pinnacle usuwana metoda z config (devig),
walidacja = sezony do 2024/25, holdout = 2025/26 i biezacy. Inne progi tylko informacyjnie.
Wszystko liczone z kursow dostepnych przed meczem (Bet365 i Pinnacle sprzed meczu); zamkniecie tylko do oceny.
Uzycie: python backtest/value/value_vs_sharp.py"""
import io
import json
import sys

sys.path.insert(0, ".")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from typer import config  # noqa: E402
from typer.betting.devig import devig_rows  # noqa: E402
from typer.ingest import footballdata_uk as fd  # noqa: E402
from typer.metrics.scores import paired_diff_ci  # noqa: E402

LEAGUES = ["E0", "D1", "F1", "I1", "SP1"]
SEASONS = [f"{y}-{str(y + 1)[2:]}" for y in range(2012, 2027)]
THRESHOLDS = (0.0, 0.01, 0.02, 0.04, 0.06)
CANDIDATE = 0.02
TAX = 0.12            # Polska: podatek od stawki, kurs efektywny = kurs * 0.88
M = {"1X2": (["B365H", "B365D", "B365A"], ["PSH", "PSD", "PSA"], ["PSCH", "PSCD", "PSCA"]),
     "OU2.5": (["B365>2.5", "B365<2.5"], ["P>2.5", "P<2.5"], ["PC>2.5", "PC<2.5"])}


def load() -> pd.DataFrame:
    parts = []
    for lg in LEAGUES:
        code = config.leagues()[lg]["fduk"]["code"]
        for s in SEASONS:
            try:
                raw = fd.download_season(code, s)
            except Exception as e:          # brak pliku sezonu (np. przyszly)
                print(lg, s, "brak:", e)
                continue
            df = pd.read_csv(io.StringIO(raw.decode("utf-8-sig", errors="replace")), on_bad_lines="skip")
            df = df.dropna(subset=["FTHG", "FTAG"]) if "FTHG" in df else df.iloc[0:0]
            if df.empty:
                continue
            df["league"], df["season"] = lg, s
            parts.append(df)
    return pd.concat(parts, ignore_index=True)


def bets(df: pd.DataFrame, method: dict) -> pd.DataFrame:
    rows = []
    goals = df["FTHG"].astype(float) + df["FTAG"].astype(float)
    res = np.select([df["FTHG"] > df["FTAG"], df["FTHG"] == df["FTAG"]], [0, 1], 2)
    for mkt, (soft, pre, close) in M.items():
        if not all(c in df.columns for c in soft + pre + close):
            continue
        S = df[soft].apply(pd.to_numeric, errors="coerce").to_numpy(float)
        P = devig_rows(df[pre].apply(pd.to_numeric, errors="coerce").to_numpy(float), method[mkt])
        C = devig_rows(df[close].apply(pd.to_numeric, errors="coerce").to_numpy(float), method[mkt])
        y = res if mkt == "1X2" else np.where(goals > 2.5, 0, 1)
        ok = np.isfinite(S).all(1) & np.isfinite(P).all(1) & np.isfinite(C).all(1)
        edge = S * P - 1
        for k in range(S.shape[1]):
            for i in np.where(ok & (edge[:, k] > min(THRESHOLDS)))[0]:
                rows.append(dict(match=i, league=df["league"].iat[i], season=df["season"].iat[i], market=mkt, sel=k,
                                 odds=S[i, k], edge=edge[i, k], clv=S[i, k] * C[i, k] - 1,
                                 win=int(y[i] == k)))
    b = pd.DataFrame(rows)
    # jeden zaklad na mecz i rynek: najwieksza przewaga (bez obstawiania dwoch wynikow naraz)
    b = b.sort_values("edge", ascending=False).drop_duplicates(["match", "market"]).sort_index()
    b["profit"] = np.where(b["win"] == 1, b["odds"] - 1, -1.0)
    b["profit_tax"] = np.where(b["win"] == 1, b["odds"] * (1 - TAX) - 1, -1.0)
    return b


def summary(b: pd.DataFrame) -> dict:
    if b.empty:
        return dict(n=0)
    clv, roi, roit = (paired_diff_ci(b[c].to_numpy()) for c in ("clv", "profit", "profit_tax"))
    return dict(n=int(len(b)), clv=clv, roi=roi, roi_z_podatkiem=roit, sr_kurs=float(b["odds"].mean()),
                trafione=float(b["win"].mean()))


if __name__ == "__main__":
    dv = config.model_params().get("devig", {}).get("zamkniecie", {"1X2": "shin", "OU2.5": "power"})
    df = load()
    print("mecze:", len(df), df.groupby("league").size().to_dict(), flush=True)
    all_b = bets(df, dv)
    hold = all_b["season"].isin(["2025-26", "2026-27"])
    out = {"devig": dv, "kandydat_prog": CANDIDATE, "walidacja": {}, "holdout": {}}
    for name, part in (("walidacja", all_b[~hold]), ("holdout", all_b[hold])):
        for t in THRESHOLDS:
            s = part[part["edge"] > t]
            out[name][f"prog_{t:g}"] = dict(razem=summary(s),
                                           per_rynek={m: summary(g) for m, g in s.groupby("market")},
                                           per_liga={lg: summary(g) for lg, g in s.groupby("league")})
    cand = out["walidacja"][f"prog_{CANDIDATE:g}"]["razem"], out["holdout"][f"prog_{CANDIDATE:g}"]["razem"]
    for nm, c in zip(("walidacja", "holdout"), cand):
        print(nm, json.dumps(c, default=float))
    for t in THRESHOLDS:
        v = out["walidacja"][f"prog_{t:g}"]["razem"]
        print(f"prog {t:.2f}: n {v['n']}, CLV {v['clv']['mean']:+.4f}, ROI {v['roi']['mean']:+.4f}", flush=True)
    json.dump(out, open("backtest/value/value_vs_sharp.json", "w"), indent=1, default=float)
