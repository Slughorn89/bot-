"""Baza: predykcje i zaklady tylko do dopisywania, upserty idempotentne."""
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from typer.store import db


def _pred(**kw):
    return dict(dict(event_id="E1", market="1X2", selection="1", p_model=0.5, model_version="v1",
                     role="champion", kickoff_utc=datetime(2024, 8, 17, 14, tzinfo=timezone.utc)), **kw)


def test_predictions_append_only(tmp_engine):
    (pid,) = db.append(tmp_engine, db.predictions, [_pred()])
    with pytest.raises(sa.exc.DatabaseError):
        with tmp_engine.begin() as c:
            c.execute(db.predictions.update().where(db.predictions.c.id == pid).values(p_model=0.9))
    with pytest.raises(sa.exc.DatabaseError):
        with tmp_engine.begin() as c:
            c.execute(db.predictions.delete())
    df = db.read_df(tmp_engine, "SELECT p_model FROM predictions")
    assert df["p_model"].tolist() == [0.5]


def test_bets_append_only(tmp_engine):
    db.append(tmp_engine, db.bets, [dict(prediction_id=1, event_id="E1", market="1X2", selection="1",
                                         odds=2.1, edge=0.05, stake_frac=0.01)])
    with pytest.raises(sa.exc.DatabaseError):
        with tmp_engine.begin() as c:
            c.execute(db.bets.update().values(odds=5.0))


def test_store_matches_idempotentne(tmp_engine, synth):
    part = synth.head(50)
    s1 = db.store_matches(tmp_engine, part)
    db.store_matches(tmp_engine, part)
    n = db.read_df(tmp_engine, "SELECT count(*) AS n FROM events")["n"][0]
    no = db.read_df(tmp_engine, "SELECT count(*) AS n FROM odds_snapshots")["n"][0]
    assert n == 50 and no == s1["odds"]
