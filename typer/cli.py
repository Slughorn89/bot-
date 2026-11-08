#!/usr/bin/env python3
"""Typer pilkarski: wiersz polecen.

  python cli.py fetch    [--as-of RRRR-MM-DD]   historia + terminarz + kursy do bazy
  python cli.py snapshot                        kursy z The Odds API (typ / zamkniecie), w budzecie
  python cli.py lineups                         sklady i kontuzje z API-Football (tylko zbieranie)
  python cli.py betfair-close                   zamkniecie Betfair z OddsRelay (cron co 5 min, zapytanie tylko przed meczem)
  python cli.py adapters                        rejestr adapterow warstwy danych (licencje, wlaczone)
  python cli.py ingest NAZWA [--param k=v]      adapter -> rekordy z available_at -> baza
  python cli.py budget                          zuzycie limitow API i szacunek kredytow
  python cli.py predict  [--as-of ...]          predykcje (niezmienialne) + zaklady papierowe
  python cli.py settle   [--as-of ...]          wyniki, rozliczenie, dziennik bledow
  python cli.py learn                           przeglad tygodniowy (evaluate.py od daty wdrozenia)
  python cli.py report   [--as-of ...] [--send] raport dzienny (Telegram, opcjonalnie webhook n8n)
  python cli.py preview  [--send]              wstepne typy na 3 dni (bez zapisu, opcjonalnie Telegram)
  python cli.py telegram-setup                 polacz z botem Telegrama (token w .env)
  python cli.py backtest [--layers X] [--holdout] [--compare]
  python cli.py tune                            strojenie ocen online na walidacji
  python cli.py goals [--half-life 480 --w-xg 0.2]   model goli: warianty, wybor per liga
  python cli.py corners [--holdout]             model rozne: z efektem stanu gry i bez, roznica log loss z CI
  python cli.py calibrate                       modul 6: marza, kalibracja po ECE, blend per liga, CLV i ROI z CI
  python cli.py analyze  [--league POL --market 1X2 --since ... --csv plik]  analiza (sekcja 14)
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


def cmd_snapshot(a):
    from typer.pipeline import daily
    print(daily.snapshot_odds(_engine()))


def cmd_adapters(a):
    """Rejestr adapterow warstwy danych: licencja, czy wlaczony, typy rekordow."""
    from typer.ingest.core.adapter import license_mode, load_all
    print(f"licencja_uzycia: {license_mode()}")
    for name, c in sorted(load_all().items()):
        on = (config.sources().get(name) or {}).get("wlaczony", c.enabled_by_default)
        print(f"  {name:17} {'wlaczony' if on else 'WYLACZONY':9} {'NIEKOMERCYJNA ' if c.non_commercial else ''}"
              f"{c.license} | rekordy: {', '.join(t.__name__ for t in c.record_types)}")


def cmd_ingest(a):
    """Pobranie przez adapter -> walidacja (available_at) -> baza, z audytem pobran."""
    from typer.ingest.core.adapter import load_all
    from typer.ingest.core.store import store_audit, store_records
    params = {}
    for kv in a.param or []:
        k, v = kv.split("=", 1)
        params[k] = json.loads(v) if v[:1] in "[{0123456789-" or v in ("true", "false") else v
    ad = load_all()[a.name]()
    recs = ad.records(**params)
    eng = _engine()
    print(dict(zapisane=store_records(eng, recs), audyt=store_audit(eng, ad.client.audit)))


def cmd_betfair_close(a):
    """Zamkniecie Betfair do CLV; zapytanie tylko, gdy mecz startuje w ciagu 10 min (cron co 5 min)."""
    from typer.pipeline import daily
    print(daily.betfair_close(_engine()))


def cmd_lineups(a):
    from typer.pipeline import daily
    print(daily.collect_lineups(_engine()))


def cmd_budget(a):
    """Budzet zapytan: zuzycie z ksiegi + szacunek kredytow The Odds API z historii godzin startu."""
    from datetime import datetime, timezone
    from typer.ingest.budget import Ledger, history_estimate, next_reset
    from typer.pipeline.data import load_matches
    now = datetime.now(timezone.utc)
    led = Ledger()
    for src in ("the_odds_api", "api_football"):
        print(f"{src}: zuzyte {led.used(src, now)}, zostalo (z rezerwa) {led.remaining(src, now)}, "
              f"reset {next_reset(src, now):%Y-%m-%d}")
    h = history_estimate(load_matches(), a.season)
    if len(h):
        print(f"\nSzacunek The Odds API dla planu snapshotow na sezonie {a.season}:")
        print(h.to_string())
        print(f"srednio {h['kredyty'].mean():.0f}, maks {h['kredyty'].max()} kredytow/miesiac (limit 500)")


def cmd_predict(a):
    from typer.pipeline import daily
    eng = _engine()
    preds = daily.predict(eng, as_of=a.as_of, lead_minutes=getattr(a, "lead_minutes", None))
    bets = daily.place_bets(eng, preds) if len(preds) else preds
    per_role = preds.groupby("role").size().to_dict() if len(preds) else {}
    print(f"predykcje: {len(preds)} wierszy {per_role}, zaklady papierowe (tylko champion): {len(bets)}")
    if len(bets) and not a.as_of:  # tryb odtworzeniowy (backtest dnia) nie spamuje Telegrama
        from typer.report import daily as rep
        msg = rep.notify_bets(eng, bets)
        if msg:
            print(msg)


def cmd_preview(a):
    """Wstepne typy na 3 dni bez zapisu do bazy (nie psuje CLV ani wlasciwego typu przed meczem)."""
    from typer.pipeline import daily
    from typer.report import render, telegram
    preds, chosen = daily.preview(_engine())
    msgs = render.render_preview(preds, chosen, config.sports()["football"]["timezone"])
    print("\n\n".join(msgs))
    if a.send:
        if not telegram.configured():
            print("Brak TELEGRAM_BOT_TOKEN albo TELEGRAM_CHAT_ID w .env. Najpierw: python cli.py telegram-setup")
            sys.exit(2)
        print(f"Telegram: wyslano {telegram.send_messages(msgs)} wiadomosci")


def cmd_telegram_setup(a):
    from typer.report import telegram
    print(telegram.setup())


def cmd_telegram_test(a):
    from typer.report import telegram
    if not telegram.configured():
        print("Brak TELEGRAM_BOT_TOKEN albo TELEGRAM_CHAT_ID w .env. Najpierw: python cli.py telegram-setup")
        sys.exit(2)
    telegram.send_messages(["Test typera: jesli to widzisz, wysylka dziala."])
    print("wyslano wiadomosc testowa")


def cmd_settle(a):
    from typer.pipeline import daily
    print(daily.settle_day(_engine(), as_of=a.as_of))


def cmd_report(a):
    """Jeden JSON -> CLI / Telegram / HTML (sekcja 13)."""
    from typer.report import daily as rep
    from typer.report import render
    if getattr(a, "from_json", None):  # dowolny JSON z evaluate.py (np. backtest) -> HTML i pasek bramek
        data = json.loads(open(a.from_json, encoding="utf-8").read())
        view = rep.from_evaluation(data, csv=a.csv)
        page = render.render_html_evaluation(data, f"Raport typera: {a.from_json}")
        out = a.html or str(config.ROOT / "live" / "evaluation.html")
        (config.ROOT / "live").mkdir(exist_ok=True)
        open(out, "w", encoding="utf-8").write(page)
        print(render.render_cli_weekly(view, title="RAPORT Z OCENY"))
        print(f"HTML: {out}")
        return
    eng = _engine()
    if getattr(a, "weekly", False):
        w = rep.build_weekly(eng)
        print(render.render_cli_weekly(w))
        if w.get("ocena"):
            out = a.html or str(config.ROOT / "live" / f"weekly_{w['data']}.html")
            open(out, "w", encoding="utf-8").write(render.render_html_evaluation(w["ocena"], "Przegląd tygodniowy"))
            print(f"HTML: {out}")
        return
    text, payload = rep.build(eng, day=a.as_of)
    print(text)
    if getattr(a, "html", None):
        open(a.html, "w", encoding="utf-8").write(render.render_html_daily(payload))
    if a.send:
        print(rep.send(text, payload))


def cmd_day(a):
    for f in (cmd_fetch, cmd_predict, cmd_settle):
        f(a)
    a.send = getattr(a, "send", False)
    a.weekly, a.from_json, a.html = False, None, None
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


def cmd_analyze(a):
    """Analiza wynikow (sekcja 14): pytanie -> dane (Zalacznik B) -> evaluate.py --by -> walidacja -> tokeny.
    Zrodlo: baza (predykcje na zywo) albo --csv (np. plik z backtestu)."""
    import tempfile
    import pandas as pd
    from typer.learn import settle
    from typer.pipeline.backtest import run_evaluate
    from typer.report import daily as rep
    from typer.report import render
    print(f"PYTANIE: metryka={a.metric} | segment={a.league or 'wszystkie'}/{a.market or 'wszystkie'} | "
          f"okres={a.since or 'od poczatku'}..{a.until or 'dzis'} | wersja={a.version or 'champion'}")
    with tempfile.TemporaryDirectory() as td:
        src = a.csv
        if not src:
            src = f"{td}/live.csv"
            settle.export_preds(_engine(), src, role="champion", since=a.since, version=a.version)
        df = pd.read_csv(src)
        if a.version and "model_version" in df.columns:
            df = df[df["model_version"] == a.version]
        if a.league:
            df = df[df["league"].isin(a.league.split(","))]
        if a.market:
            df = df[df["market"].isin(a.market.split(","))]
        if df.empty:
            sys.exit("brak danych dla tego pytania")
        csv, js = f"{td}/q.csv", f"{td}/q.json"
        df.to_csv(csv, index=False)
        vt = config.gates().get("value_threshold") if "odds_taken" in df.columns and "stake" not in df.columns else None
        code, txt = run_evaluate(csv, since=a.since, until=a.until, by=a.by, json_out=js, value_threshold=vt)
        if code == 3:
            sys.exit(txt)
        data = json.loads(open(js, encoding="utf-8").read())
        print(render.render_cli_weekly(rep.from_evaluation(data, csv=csv), title="ANALIZA"))
        if a.html:
            open(a.html, "w", encoding="utf-8").write(render.render_html_evaluation(data, "Analiza"))
            print(f"HTML: {a.html}")
    print("Pulapki (14.3): wnioski o segmentach potwierdzaj na nowym okresie albo z korekta; pokazuj calosc "
          "i rozbicie (Simpson); filtruj po wersji modelu; ROI tylko z przedzialem.")


def cmd_goals(a):
    """Modul 2: walk forward modelu goli na walidacji + wybor wariantu per liga vs oceny online."""
    import pandas as pd
    from typer.pipeline.backtest import params_from_config
    from typer.pipeline.data import load_matches, split_dates
    from typer.pipeline.engine import Engine
    from typer.pipeline.goal_backtest import run, select_per_league
    from typer.pipeline.layers import metrics
    sd = split_dates()
    df = load_matches()
    out = run(df, sd["walidacja_od"], sd["walidacja_do"], a.half_life, a.w_xg, use_context=not a.no_context)
    on = Engine(params_from_config(), collect_features=False).run(df, predict_from=sd["walidacja_od"])
    on = on[pd.to_datetime(on["date"]) <= pd.Timestamp(sd["walidacja_do"])]
    cands = {"online": on, **{v: g for v, g in out.groupby("variant")}}
    for k, c in cands.items():
        m = metrics(c)
        print(f"{k:10} n={int(m['n'])} 1X2 {m['ll_1x2']:.4f} O/U {m['ll_ou']:.4f} BTTS {m['ll_btts']:.4f} "
              f"J {m['ll_1x2'] + 0.5 * (m['ll_ou'] + m['ll_btts']):.5f}")
    print(select_per_league(cands, default="online").to_string(index=False))


def cmd_corners(a):
    """Modul 3: walk forward modelu rożnych, wersje baseline / A0 / A / B, roznica log loss z CI90 i CI95."""
    from typer.pipeline.corner_backtest import compare, run
    from typer.pipeline.data import load_matches, split_dates
    sd = split_dates()
    cc = config.model_params().get("corner_models", {})
    start, end = (sd["holdout_od"], "2100-01-01") if a.holdout else (sd["walidacja_od"], sd["walidacja_do"])
    res = run(load_matches(extended=True), start, end, half_life=cc.get("half_life", 365),
              ridge=cc.get("ridge", 3.0), use_style=cc.get("use_style", False), n_sims=cc.get("n_sims", 20000))
    print(res.groupby("variant")[[c for c in res.columns if c.startswith("ll_")]].mean().round(5).to_string())
    for x, y in (("A", "B"), ("A0", "A"), ("baseline", "A"), ("baseline", "B")):
        print(compare(res, x, y, by_league=(x, y) == ("A", "B")).to_string(index=False))


def cmd_calibrate(a):
    """Modul 6: pelny przebieg (backtest/calibration/run_m6.py), wynik w m6.json i reports/calibration/."""
    import subprocess
    subprocess.run([sys.executable, str(config.ROOT / "backtest" / "calibration" / "run_m6.py")], cwd=config.ROOT,
                   check=True)


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
            p.add_argument("--send", action="store_true", help="wyslij raport na Telegram (i webhook n8n, jesli ustawiony)")
        if name == "report":
            p.add_argument("--weekly", action="store_true", help="przeglad tygodniowy (sekcja 9.3)")
            p.add_argument("--from-json", default=None, help="wyrenderuj JSON z evaluate.py (np. backtest)")
            p.add_argument("--html", default=None, help="zapisz widok HTML do pliku")
            p.add_argument("--csv", default=None, help="z --from-json: plik predykcji (luka do rynku, kontrole)")
        if name == "predict":
            p.add_argument("--lead-minutes", type=int, default=None,
                           help="typuj tylko mecze startujace w ciagu N minut (na zywo: 90)")
    sub.add_parser("learn")
    p = sub.add_parser("preview", help="wstepne typy na 3 dni, bez zapisu do bazy (nie sa zakladami)")
    p.add_argument("--send", action="store_true", help="wyslij podglad na Telegram")
    sub.add_parser("telegram-setup", help="znajdz chat_id z wiadomosci do bota, zapisz w .env, wyslij test")
    sub.add_parser("telegram-test", help="wyslij wiadomosc testowa na Telegram")
    sub.add_parser("snapshot", help="snapshot kursow z The Odds API (w chwili typu i zamkniecia)")
    sub.add_parser("lineups", help="sklady i kontuzje z API-Football (60-75 min przed meczem)")
    sub.add_parser("betfair-close", help="zamkniecie Betfair z OddsRelay do CLV (tylko mecze w ciagu 10 min)")
    sub.add_parser("adapters", help="rejestr adapterow warstwy danych (modul 1)")
    p = sub.add_parser("ingest", help="pobierz przez adapter i zapisz rekordy (z available_at)")
    p.add_argument("name")
    p.add_argument("--param", action="append", help='parametr adaptera, np. --param tour=m --param \'kinds=["matches"]\'')
    p = sub.add_parser("budget", help="zuzycie i szacunek budzetu zapytan API")
    p.add_argument("--season", default="2025-26")
    p = sub.add_parser("backtest")
    p.add_argument("--layers", default=config.model_params().get("layers", "online+cal"))
    p.add_argument("--holdout", action="store_true")
    p.add_argument("--force-holdout", action="store_true")
    p.add_argument("--compare", default=None, help="lista zestawow warstw po przecinku (walidacja)")
    p = sub.add_parser("analyze", help="analiza wynikow (sekcja 14)")
    p.add_argument("--csv", default=None, help="plik predykcji (Zalacznik B); bez tego: baza")
    p.add_argument("--league", default=None)
    p.add_argument("--market", default=None)
    p.add_argument("--since", default=None)
    p.add_argument("--until", default=None)
    p.add_argument("--version", default=None)
    p.add_argument("--by", default="league,market")
    p.add_argument("--metric", default="log loss, CLV, ECE")
    p.add_argument("--html", default=None)
    p = sub.add_parser("goals", help="modul 2: model goli (DC / dwuwymiarowy Poisson / NB), wybor per liga")
    p.add_argument("--half-life", type=float, default=480)
    p.add_argument("--w-xg", type=float, default=0.2)
    p.add_argument("--no-context", action="store_true")
    p = sub.add_parser("corners", help="modul 3: rozne, wersja z efektem stanu gry i bez")
    p.add_argument("--holdout", action="store_true")
    sub.add_parser("calibrate", help="modul 6: kalibracja, marza, blend per liga, CLV i ROI z CI")
    p = sub.add_parser("tune")
    p.add_argument("--rounds", type=int, default=4)
    p = sub.add_parser("journal")
    p.add_argument("--classify", nargs=2, metavar=("ID", "KLASA"))
    p.add_argument("--note", default=None)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    globals()[f"cmd_{a.cmd.replace('-', '_')}"](a)


if __name__ == "__main__":
    main()
