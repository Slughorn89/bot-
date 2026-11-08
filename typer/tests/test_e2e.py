"""End to end na malym zbiorze testowym: pobranie, predykcja, zaklady, rozliczenie, raport, evaluate.py."""
import os
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
        n_var = len(daily.variants())
        assert len(preds) == st["fixtures"] * 7 * n_var  # (1X2 3 + O/U 2 + BTTS 2) x wersje modelu
        assert set(preds["role"]) == ({"champion", "challenger"} if n_var > 1 else {"champion"})
        p1 = preds[preds["market"] == "1X2"].groupby(["event_id", "model_version"])["p_model"].sum()
        assert ((p1 - 1).abs() < 1e-9).all()
        bets = daily.place_bets(tmp_engine, preds)
        if len(bets):  # challenger nigdy nie gra
            champ = set(preds.loc[preds["role"] == "champion", "id"])
            assert set(bets["prediction_id"]) <= champ
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
    assert len(df) == total_preds // len(daily.variants())  # eksport championa
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "evaluate.py"), str(csv),
                        "--json", str(tmp_path / "r.json")], capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONUTF8": "1"})
    assert p.returncode in (0, 1, 2), p.stderr
    rep_json = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
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
                        str(tmp_path / "r.json")], capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONUTF8": "1"})
    rep_json = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    gates = {g["bramka"]: g["wynik"] for g in rep_json["bramki"]}
    assert gates["lepszy_od_baseline"] == "OK"
    assert gates["spojnosc_prawdopodobienstw"] == "OK"


def test_podglad_niczego_nie_zapisuje(patched, tmp_engine, synth):
    """cli.py preview: predykcje i kandydaci bez zapisu, wiec wlasciwy typ przed meczem nie jest blokowany."""
    from typer.report import render
    from typer.store import db
    daily, _ = patched
    d = sorted(d for d in synth["date"].unique() if pd.Timestamp(d) >= pd.Timestamp("2018-09-01"))[0]
    st = daily.fetch(tmp_engine, as_of=d)
    counts = lambda: [len(db.read_df(tmp_engine, f"SELECT * FROM {t}"))
                      for t in ("predictions", "bets", "model_registry", "features")]
    before = counts()
    preds = daily.predict(tmp_engine, as_of=d, role="champion", dry=True)
    assert len(preds) == st["fixtures"] * 7 and counts() == before
    msgs = render.render_preview(preds, [], "Europe/Warsaw")
    assert msgs[0].startswith("WSTĘPNE TYPY") and " / " in msgs[1]
    real = daily.predict(tmp_engine, as_of=d, role="champion")
    assert len(real) == len(preds)  # podglad nie zajal miejsca wlasciwej predykcji


def test_typy_wstecz_bez_zapisu(patched, synth):
    """cli.py history: symulacja na rozegranych meczach, wynik i bilans, bez bazy."""
    from typer.report import render
    daily, _ = patched
    end = pd.Timestamp(max(synth["date"])) + pd.Timedelta(days=1)
    h = daily.history(weeks=4, today=end, matches=synth)
    assert h["mecze"] > 0
    for t in h["typy"]:
        assert pd.Timestamp(t["data"]) >= end - pd.Timedelta(days=28) and t["trafiony"] in (0, 1)
        assert t["edge"] >= 0.05
    assert len(h["lista"]) == h["mecze"]  # kazdy rozegrany mecz z faworytem modelu, nawet bez typow
    msgs = render.render_history(h)
    assert msgs[0].startswith("TYPY WSTECZ") and all(len(m) <= render.TG_LIMIT for m in msgs)


def test_typy_na_kazdy_mecz_z_kursem(patched, tmp_engine, synth):
    """cli.py tips: kazdy mecz z terminarza dostaje faworyta 1X2 i strone O/U z kursem; nic nie zapisuje."""
    from typer.report import render
    from typer.store import db
    daily, _ = patched
    d = sorted(d for d in synth["date"].unique() if pd.Timestamp(d) >= pd.Timestamp("2018-09-01"))[0]
    st = daily.fetch(tmp_engine, as_of=d)
    t = daily.tips(tmp_engine, hours=48, now=pd.Timestamp(d).tz_localize("UTC"), as_of=d)
    assert len(t) == st["fixtures"] and len(db.read_df(tmp_engine, "SELECT * FROM predictions")) == 0
    for x in t:
        assert x["1x2"]["selection"] in ("1", "X", "2") and x["1x2"]["p"] >= 1 / 3 - 1e-9
        assert x["ou"]["selection"] in ("over2.5", "under2.5") and x["ou"]["p"] >= 0.5 - 1e-9
        if x["1x2"]["odds"]:
            assert abs(x["1x2"]["edge"] - (x["1x2"]["p"] * x["1x2"]["odds"] - 1)) < 1e-9
    msgs = render.render_tips(t, "Europe/Warsaw")
    assert msgs[0].startswith("TYPY NA NAJBLIŻSZE") and "Najpewniejsze" in msgs[0]
    assert all(len(m) <= render.TG_LIMIT for m in msgs)
    assert "Brak meczów" in render.render_tips([], "Europe/Warsaw")[0]
