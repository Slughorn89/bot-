"""Regresja: zamrozony backtest ocen online na walidacji. Metryki nie moga sie pogorszyc
bez nowego wpisu w experiments.md i aktualizacji tests/regression_reference.json.
Wymaga danych w cache (data/matches.pkl, tworzy go `python cli.py backtest`); bez nich test jest pomijany."""
import json
from pathlib import Path

import pandas as pd
import pytest

from typer import config

REF = Path(__file__).parent / "regression_reference.json"
TOL = 1e-4

pytestmark = pytest.mark.slow


@pytest.mark.skipif(not (config.DATA_DIR / "matches.pkl").exists(), reason="brak danych w cache")
def test_metryki_walidacji_nie_gorsze():
    from typer.pipeline.backtest import params_from_config
    from typer.pipeline.data import load_matches
    from typer.pipeline.engine import Engine
    from typer.pipeline.layers import metrics
    ref = json.loads(REF.read_text(encoding="utf-8"))
    if config.sources()["xgabora"]["ref"] != ref["data_ref"]:
        pytest.skip("inny commit danych niz w referencji: przelicz referencje i opisz w experiments.md")
    start, end = ref["okres"].split("..")
    res = Engine(params_from_config(), collect_features=False).run(load_matches(), predict_from=start)
    res = res[pd.to_datetime(res["date"]) <= pd.Timestamp(end)]
    m = metrics(res)
    m["ece"] = ece_of(res)
    assert m["n"] == ref["n"]
    for k in ("ll_1x2", "ll_ou", "ll_btts", "ece"):
        assert m[k] <= ref[k] + TOL, f"{k}: {m[k]:.5f} > referencja {ref[k]:.5f}"


def ece_of(frame) -> float:
    """ECE dokladnie tak, jak liczy go tools/evaluate.py (na wierszach selekcji)."""
    import sys
    sys.path.insert(0, str(config.ROOT / "tools"))
    import evaluate
    from typer.pipeline.backtest import to_preds
    f = frame.copy()
    for c in ("bench_h", "bench_d", "bench_a"):
        if c not in f.columns:
            f[c] = float("nan")
    preds, _ = to_preds(f, "regresja")
    return float(evaluate.ece(preds["p_model"].to_numpy(), preds["outcome"].to_numpy())[0])
