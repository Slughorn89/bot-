#!/usr/bin/env python3
"""Typer pilkarski: wiersz polecen.

  python cli.py fetch    [--as-of RRRR-MM-DD]   historia + terminarz + kursy do bazy
  python cli.py predict  [--as-of ...]          predykcje (niezmienialne) + zaklady papierowe
  python cli.py settle   [--as-of ...]          wyniki, rozliczenie, dziennik bledow
  python cli.py learn                           przeglad tygodniowy (evaluate.py od daty wdrozenia)
  python cli.py report   [--as-of ...] [--send] raport dzienny (+ webhook n8n)
  python cli.py backtest [--layers X] [--holdout] [--compare]
  python cli.py tune                            strojenie ocen online na walidacji
  python cli.py journal  [--classify ID KLASA --note TEKST]
  python cli.py day      --as-of RRRR-MM-DD     caly cykl dnia w trybie odtworzeniowym
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from typer import config


def _engine():
    from typer.store import db
    eng = db.get_engine()
    db.init_db(eng)
    return eng


def cmd_fetch(a):
    from typer.pipeline import daily
    print(daily.fetch(_engine(), as_of=a.as_of))


def cmd_predict(a):
    from typer.pipeline import daily
    eng = _engine()
    preds = daily.predict(eng, as_of=a.as_of)
    bets = daily.place_bets(eng, preds) if len(preds) else preds
    print(f"predykcje: {len(preds)} wierszy, zaklady papierowe: {len(bets)}")


def cmd_settle(a):
    from typer.pipeline import daily
    print(daily.settle_day(_engine(), as_of=a.as_of))


def cmd_report(a):
    from typer.report import daily as rep
    text, payload = rep.build(_engine(), day=a.as_of)
    print(text)
    if a.send:
        print(rep.send(text, payload))


def cmd_day(a):
    for f in (cmd_fetch, cmd_predict, cmd_settle):
        f(a)
    a.send = getattr(a, "send", False)
    cmd_report(a)


def cmd_learn(a):
    """Przeglad tygodniowy: evaluate.py na predykcjach na zywo od daty wdrozenia championa."""
    from typer.learn import settle
    from typer.learn.champion import compare, current
    from typer.pipeline.backtest import run_evaluate
    eng = _engine()
    champ = current(eng)
    if not champ:
        sys.exit("brak championa w model_registry (uruchom najpierw predict)")
    since = champ["drift_reference_date"]
    path = config.ROOT / "live" / "preds.csv"
    path.parent.mkdir(exist_ok=True)
    df = settle.export_preds(eng, path, role="champion", since=since)
    if df.empty:
        sys.exit("brak rozliczonych predykcji od daty wdrozenia")
    code, rep = run_evaluate(path, since=since, json_out=config.ROOT / "live" / "weekly.json")
    print(rep)
    chal = current(eng, "challenger")
    if chal:
        s = settle.settled(eng, role=None, since=since)
        print("challenger vs champion:", compare(s, champ["version"], chal["version"]))


def cmd_backtest(a):
    from typer.pipeline import backtest as bt
    if a.compare:
        from typer.pipeline.layers import metrics
        frame = bt.build_frame()
        rows = []
        for name in a.compare.split(","):
            r = bt.run(name, frame=frame)
            m = r["metrics"]
            rows.append(dict(warstwy=name, kod=r["code_preds"], kod_rynek=r["code_market"],
                             **{k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()}))
            print(json.dumps(rows[-1], default=float))
        return
    r = bt.run(a.layers, holdout=a.holdout, force_holdout=a.force_holdout)
    print(r["report_preds"])
    print("=" * 80, "\nBENCHMARK RYNKU (log loss vs rynek, bramka brak_wycieku)\n")
    print(r["report_market"])
    print("WERDYKT LACZNY:", bt.combined_verdict(r["code_preds"], r["code_market"]))
    sys.exit(max(r["code_preds"], r["code_market"]))


def cmd_tune(a):
    from typer.pipeline.data import load_matches, split_dates
    from typer.pipeline.tune import coordinate_search
    sd = split_dates()
    best, j, _ = coordinate_search(load_matches(), sd["walidacja_od"], sd["walidacja_do"], rounds=a.rounds,
                                   log_path=config.ROOT / "backtest" / "tune_history.json")
    print(json.dumps(dict(J=j, params=best.to_dict()), indent=1))


def cmd_journal(a):
    from typer.learn import journal
    from typer.store import db
    eng = _engine()
    if a.classify:
        journal.classify(eng, int(a.classify[0]), a.classify[1], a.note or "")
        print("zapisano")
        return
    print(db.read_df(eng, "SELECT id, event_id, market, round(p_actual, 4) AS p, suggested_class, "
                          "final_class, note FROM error_journal ORDER BY id DESC LIMIT 30").to_string(index=False))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Typer pilkarski")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "predict", "settle", "report", "day"):
        p = sub.add_parser(name)
        p.add_argument("--as-of", default=None, help="tryb odtworzeniowy: udawaj, ze dzis jest ten dzien")
        if name in ("report", "day"):
            p.add_argument("--send", action="store_true", help="wyslij JSON na webhook n8n")
    sub.add_parser("learn")
    p = sub.add_parser("backtest")
    p.add_argument("--layers", default=config.model_params().get("layers", "online+cal"))
    p.add_argument("--holdout", action="store_true")
    p.add_argument("--force-holdout", action="store_true")
    p.add_argument("--compare", default=None, help="lista zestawow warstw po przecinku (walidacja)")
    p = sub.add_parser("tune")
    p.add_argument("--rounds", type=int, default=4)
    p = sub.add_parser("journal")
    p.add_argument("--classify", nargs=2, metavar=("ID", "KLASA"))
    p.add_argument("--note", default=None)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    globals()[f"cmd_{a.cmd}"](a)


if __name__ == "__main__":
    main()
