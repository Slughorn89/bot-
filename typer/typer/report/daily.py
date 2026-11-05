"""Raport dzienny (sekcja 11) i tygodniowy (9.3) jako JSON (schema typer.report/v2 + dane typow z bazy).
Wszystkie widoki (CLI, Telegram, HTML) renderuje typer/report/render.py z TEGO JSON-a.
Liczby wylacznie z bazy i z tools/evaluate.py."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import sqlalchemy as sa

from typer import config
from typer.learn import settle
from typer.learn.champion import current
from typer.pipeline.backtest import run_evaluate
from typer.report import render
from typer.report.analysis import segment_significance, validate_preds
from typer.store import db

LIVE_DIR = config.ROOT / "live"
SCHEMA = "typer.report/v2"


def _evaluate_module():
    sys.path.insert(0, str(config.ROOT / "tools"))
    import evaluate  # noqa: WPS433 - narzedzie z Zalacznika A, liczy log loss rynku tak samo jak bramki
    return evaluate


def evaluate_window(engine: sa.Engine, since, role: str = "champion") -> tuple[dict, dict, pd.DataFrame]:
    """(podsumowanie okna, pelny JSON evaluate.py, wyeksportowane predykcje)."""
    with tempfile.TemporaryDirectory() as td:
        csv, js = Path(td) / "preds.csv", Path(td) / "rep.json"
        df = settle.export_preds(engine, csv, role=role, since=since)
        if df.empty:
            return {}, {}, df
        code, txt = run_evaluate(csv, json_out=js, by="sport,league,market")
        if code == 3 or not js.exists():
            return dict(werdykt="ZLY PLIK (kontrakt danych)", blad=txt.strip()[-300:]), {}, df
        rep = json.loads(js.read_text())
        summ = dict(n=rep.get("zdarzenia"), ll=rep.get("ll_model"), ece=rep.get("ece"), werdykt=rep.get("werdykt"),
                    zaklady=rep.get("zaklady") or {}, okres=rep.get("okres"))
        if "odds_close" in df.columns and df["odds_close"].notna().any():
            ev = _evaluate_module()
            e, _, _ = ev.event_table(ev.add_fair_close(ev.load(str(csv))))
            em = e[e["ll_market"].notna()]
            if len(em):
                summ.update(ll_rynek=float(em["ll_market"].mean()), n_rynek=len(em),
                            luka=float(em["ll_model"].mean() - em["ll_market"].mean()))
    return summ, rep, df


def _tips(engine: sa.Engine, day, threshold: float) -> list[dict]:
    bets = db.read_df(engine, """
        SELECT b.*, p.p_model, e.league, e.home, e.away, e.kickoff_utc FROM bets b
        JOIN predictions p ON p.id = b.prediction_id JOIN events e ON e.event_id = b.event_id""")
    if bets.empty:
        return []
    bets["kickoff_utc"] = pd.to_datetime(bets["kickoff_utc"], utc=True)
    today = bets[bets["kickoff_utc"].dt.date == day].sort_values("kickoff_utc")
    snaps = db.read_df(engine, "SELECT event_id, market, selection, price, snapshot_utc FROM odds_snapshots "
                               "WHERE kind IN ('taken', 'prematch')")
    tz = config.sports()["football"]["timezone"]
    out = []
    for r in today.itertuples(index=False):
        latest = snaps[(snaps["event_id"] == r.event_id) & (snaps["market"] == r.market) &
                       (snaps["selection"] == r.selection)]
        latest = latest.sort_values("snapshot_utc")["price"].iloc[-1] if len(latest) else r.odds
        t = dict(godz=r.kickoff_utc.tz_convert(tz).strftime("%H:%M"), liga=r.league, mecz=f"{r.home} - {r.away}",
                 rynek=r.market, selekcja=r.selection, p=float(r.p_model), kurs_fair=1 / float(r.p_model),
                 kurs=float(latest), przewaga=float(r.p_model) * float(latest) - 1, stawka=float(r.stake_frac),
                 kurs_poprzedni=float(r.odds) if abs(float(latest) - float(r.odds)) >= 0.01 else None)
        out.append(render.karta_typu(t, threshold))
    return out


def _yesterday(engine: sa.Engine, day) -> dict:
    s = settle.settled(engine, role="champion")
    bets = db.read_df(engine, "SELECT b.*, e.kickoff_utc FROM bets b JOIN events e ON e.event_id = b.event_id")
    if s.empty or bets.empty:
        return {}
    b = bets.merge(s[["prediction_id", "outcome"]], on="prediction_id")
    b = b[pd.to_datetime(b["kickoff_utc"], utc=True).dt.date == day - timedelta(days=1)]
    if b.empty:
        return {}
    prof = np.where(b["outcome"] == 1, b["stake_frac"] * (b["odds"] - 1), -b["stake_frac"])
    co = settle.closing_odds(engine)
    bc = b.merge(co, on=["event_id", "market", "selection"], how="left")
    clv = (bc["odds"] / bc["odds_close_fair"] - 1).dropna()
    return dict(typy=len(b), trafione=int(b["outcome"].sum()), clv=float(clv.mean()) if len(clv) else None,
                clv_n=len(clv), wynik_j=float(prof.sum() * 100))


def build_payload(engine: sa.Engine, day=None) -> dict:
    day = pd.Timestamp(day).date() if day else datetime.now(timezone.utc).date()
    m = config.model_params()
    champ = current(engine) or {}
    ref = champ.get("drift_reference_date")
    p: dict = dict(schema=SCHEMA, typ="dzienny", data=str(day),
                   model=dict(version=champ.get("version", m.get("version")), od=ref))
    stan, rep_ref, _ = evaluate_window(engine, pd.Timestamp(ref).date()) if ref else ({}, {}, None)
    p["stan_modelu"] = dict(werdykt=stan.get("werdykt"), n=stan.get("n"), od=ref)
    p["typy"] = _tips(engine, day, m.get("value_threshold", 0.05))
    p["wczoraj"] = _yesterday(engine, day)
    p["okna"] = {}
    for days in (30, 90):
        summ, rep, _ = evaluate_window(engine, day - timedelta(days=days))
        p["okna"][str(days)] = summ
        if days == 90:
            p["segmenty"] = rep.get("segmenty", [])
    inne = []
    alerts_file = LIVE_DIR / "alerts.json"
    if alerts_file.exists():
        for a in json.loads(alerts_file.read_text())[-5:]:
            inne.append(dict(typ="źródło danych", segment="", od=a["ts"], info=a["msg"]))
    p["alarmy"] = render.alarmy(rep_ref.get("dryf", {}) if rep_ref else {}, inne)
    j = db.read_df(engine, "SELECT * FROM error_journal ORDER BY id DESC LIMIT 20")
    p["wnioski"] = []
    if len(j):
        j["created_utc"] = pd.to_datetime(j["created_utc"], utc=True)
        for r in j[j["created_utc"] >= pd.Timestamp.now(tz="UTC") - timedelta(days=1)].itertuples(index=False):
            ctx = r.context if isinstance(r.context, dict) else json.loads(r.context or "{}")
            p["wnioski"].append(f"{ctx.get('mecz', r.event_id)} {r.market} {ctx.get('selekcja', '')} "
                                f"wynik {ctx.get('wynik', '?')}: p {r.p_actual:.2f}, "
                                f"klasa {r.final_class or r.suggested_class}")
    return p


def build_weekly(engine: sa.Engine) -> dict:
    """Przeglad tygodniowy (9.3): evaluate.py od daty wdrozenia championa + korekta na wiele segmentow
    + kontrole danych z sekcji 14.2."""
    champ = current(engine) or {}
    ref = champ.get("drift_reference_date")
    summ, rep, df = evaluate_window(engine, pd.Timestamp(ref).date()) if ref else ({}, {}, pd.DataFrame())
    out = dict(schema=SCHEMA, typ="tygodniowy", data=str(datetime.now(timezone.utc).date()),
               model=dict(version=champ.get("version"), od=ref), ocena=rep, podsumowanie=summ)
    if rep:
        out["segmenty_po_korekcie"] = segment_significance(rep)
    if df is not None and len(df):
        out["kontrole_danych"] = validate_preds(df)
    return out


def from_evaluation(rep: dict, csv: str | None = None) -> dict:
    """Widok raportu z gotowego JSON-a evaluate.py (np. backtest). Z plikiem CSV dochodzi luka do
    rynku (liczona funkcjami evaluate.py), korekta Bonferroniego i kontrole danych z sekcji 14.2."""
    summ = dict(n=rep.get("zdarzenia"), ll=rep.get("ll_model"), ece=rep.get("ece"), zaklady=rep.get("zaklady"))
    out = dict(schema=SCHEMA, typ="ocena", data=(rep.get("okres") or ["?"])[-1], ocena=rep, podsumowanie=summ,
               segmenty_po_korekcie=segment_significance(rep))
    if csv:
        ev = _evaluate_module()
        df = pd.read_csv(csv)
        e, _, _ = ev.event_table(ev.add_fair_close(ev.load(csv)))
        em = e[e["ll_market"].notna()]
        if len(em):
            summ.update(ll_rynek=float(em["ll_market"].mean()), n_rynek=len(em),
                        luka=float(em["ll_model"].mean() - em["ll_market"].mean()))
        out["kontrole_danych"] = validate_preds(df)
    return out


def build(engine: sa.Engine, day=None) -> tuple[str, dict]:
    """Zgodnosc wstecz: (tekst CLI, payload)."""
    p = build_payload(engine, day)
    return render.render_cli(p), p


def send(text: str, payload: dict) -> str:
    """Zapis lokalny (JSON, TXT, HTML) i POST na webhook n8n. n8n tylko wysyla gotowe wiadomosci
    (pole telegram) i zalacznik HTML: zadnej logiki liczenia po stronie n8n."""
    LIVE_DIR.mkdir(exist_ok=True)
    tg = render.render_telegram(payload)
    page = render.render_html_daily(payload)
    body = dict(payload, tekst=text, telegram=tg, html=page)
    stem = LIVE_DIR / f"report_{payload['data']}"
    stem.with_suffix(".json").write_text(json.dumps(body, ensure_ascii=False, indent=1, default=str))
    stem.with_suffix(".txt").write_text(text)
    stem.with_suffix(".html").write_text(page)
    url = config.env("N8N_WEBHOOK_URL")
    if not url:
        return f"zapisano {stem}.json/.txt/.html (brak N8N_WEBHOOK_URL)"
    r = requests.post(url, json=json.loads(json.dumps(body, default=str)), timeout=30)
    r.raise_for_status()
    return f"wyslano na webhook ({r.status_code}) i zapisano {stem}.json/.txt/.html"
