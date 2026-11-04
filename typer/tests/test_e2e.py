"""End to end na malym zbiorze testowym: pobranie, predykcja, zaklady, rozliczenie, raport, evaluate.py."""
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def patched(monkeypatch, synth, tmp_path):
    from typer.pipeline import daily
    from typer.report import daily as rep
    monkeypatch.setattr(daily, "load_matches", lambda *a, **k: synth)
    monkeypatch.setattr(daily, "LIVE_DIR", tmp_path / "live")
    monkeypatch.setattr(daily, "ALERTS", tmp_path / "live" / "alerts.json")
    monkeypatch.setattr(rep, "LIVE_DIR", tmp_path / "live")
    return daily, rep


def test_pelny_cykl(patched, tmp_engine, synth, tmp_path):
    daily, rep = patched
    days = sorted(d for d in synth["date"].unique() if pd.Timestamp(d) >= pd.Timestamp("2018-09-01"))[:6]
    total_preds = 0
    for d in days:
        st = daily.fetch(tmp_engine, as_of=d)
        assert st["fixtures"] > 0
        preds = daily.predict(tmp_engine, as_of=d)
        assert len(preds) == st["fixtures"] * 7  # 1X2 (3) + O/U (2) + BTTS (2)
        p1 = preds[preds["market"] == "1X2"].groupby("event_id")["p_model"].sum()
        assert ((p1 - 1).abs() < 1e-9).all()
        daily.place_bets(tmp_engine, preds)
        # ponowne uruchomienie tego samego dnia nie dubluje predykcji (idempotencja bez nadpisywania)
        assert daily.predict(tmp_engine, as_of=d).empty
        out = daily.settle_day(tmp_engine, as_of=d)
        assert out["settled"] > 0
        total_preds += len(preds)
    text, payload = rep.build(tmp_engine, day=days[-1])
    assert text.startswith("TYPER")
    assert "Okno 30 / 90 dni" in text
    msg = rep.send(text, payload)
    assert "zapisano" in msg

    from typer.learn import settle
    csv = tmp_path / "live_preds.csv"
    df = settle.export_preds(tmp_engine, csv)
    assert len(df) == total_preds
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "evaluate.py"), str(csv),
                        "--json", str(tmp_path / "r.json")], capture_output=True, text=True)
    assert p.returncode in (0, 1, 2), p.stderr
    rep_json = json.loads((tmp_path / "r.json").read_text())
    assert rep_json["zdarzenia"] > 0
    # za mala proba: bramka "proba" musi to zglosic, a nie przepuscic
    assert any(g["bramka"] == "proba" and g["wynik"] == "BLAD" for g in rep_json["bramki"])


def test_evaluate_odroznia_model_od_szumu(synth, tmp_path):
    """Backtest na syntetyku: plik predykcji przechodzi przez evaluate.py i kalibracja jest OK."""
    from typer.pipeline.backtest import to_preds
    from typer.pipeline.engine import Engine
    fr = Engine().run(synth, predict_from="2017-07-01")
    fr["bench_h"] = fr["bench_d"] = fr["bench_a"] = float("nan")
    preds, mkt = to_preds(fr, "test")
    csv = tmp_path / "p.csv"
    preds.to_csv(csv, index=False)
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "evaluate.py"), str(csv), "--json",
                        str(tmp_path / "r.json")], capture_output=True, text=True)
    rep_json = json.loads((tmp_path / "r.json").read_text())
    gates = {g["bramka"]: g["wynik"] for g in rep_json["bramki"]}
    assert gates["lepszy_od_baseline"] == "OK"
    assert gates["spojnosc_prawdopodobienstw"] == "OK"
