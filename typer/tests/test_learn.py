"""learn/: rozliczenie voidu i zwrotow wedlug reguly z danych, champion/challenger (sekcja 12.1)."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from typer.learn import settle
from typer.learn.champion import compare, paired_bootstrap
from typer.store import db

KO = datetime(2024, 8, 17, 14, tzinfo=timezone.utc)


def _event(eng, eid, status, gh=None, ga=None):
    db.upsert(eng, db.events, [dict(event_id=eid, sport="football", league="E0", season="2024-25", kickoff_utc=KO,
                                    home=f"H{eid}", away=f"A{eid}", status=status, source="t")], ["event_id"])
    if gh is not None:
        db.upsert(eng, db.results, [dict(event_id=eid, fthg=gh, ftag=ga, source="t")], ["event_id"])
    db.append(eng, db.predictions, [dict(event_id=eid, market=m, selection=s, p_model=p, model_version="v1",
                                         role="champion", kickoff_utc=KO)
                                    for m, s, p in (("1X2", "1", 0.5), ("1X2", "X", 0.3), ("1X2", "2", 0.2),
                                                    ("OU3", "over3", 0.4), ("OU3", "under3", 0.6))])


def test_void_przelozony_i_przerwany_nie_sa_rozliczane(tmp_engine):
    _event(tmp_engine, "ok", "finished", 2, 0)
    _event(tmp_engine, "przerwany", "abandoned", 1, 0)   # zrodlo podaje wynik z chwili przerwania
    _event(tmp_engine, "przelozony", "postponed")
    s = settle.settled(tmp_engine)
    assert set(s["event_id"]) == {"ok"}


def test_linia_calkowita_zwrot_przy_remisie_na_linii(tmp_engine):
    assert settle.outcome("OU3", "over3", 2, 1) is None and settle.outcome("OU3", "under3", 1, 1) == 1
    _event(tmp_engine, "push", "finished", 2, 1)
    s = settle.settled(tmp_engine)
    assert set(s["market"]) == {"1X2"}  # O/U 3 przy 3 golach = zwrot, nie wchodzi do oceny


def _settled_pair(n, delta, seed=0):
    rng = np.random.default_rng(seed)
    ll_a = rng.uniform(0.6, 1.4, n)
    rows = []
    for i in range(n):
        for v, ll in (("champ", ll_a[i]), ("chal", ll_a[i] + delta + rng.normal(0, 0.05))):
            rows.append(dict(event_id=f"e{i}", market="1X2", model_version=v, outcome=1, log_loss=ll))
    return pd.DataFrame(rows)


def test_challenger_nie_awansuje_bez_300_zdarzen():
    r = compare(_settled_pair(299, -0.05), "champ", "chal")
    assert r["ci90"][1] < 0 and not r["awans"]


def test_challenger_awansuje_tylko_gdy_istotnie_lepszy():
    assert compare(_settled_pair(400, -0.05), "champ", "chal")["awans"]
    assert not compare(_settled_pair(400, +0.01), "champ", "chal")["awans"]
    assert not compare(_settled_pair(400, 0.0), "champ", "chal")["awans"]


def test_bootstrap_sparowany():
    m, lo, hi = paired_bootstrap(np.zeros(500), np.full(500, -0.1) + np.random.default_rng(1).normal(0, .01, 500))
    assert lo < m < hi < 0
