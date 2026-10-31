"""Raport dzienny (sekcja 11). Liczby wylacznie z bazy i z tools/evaluate.py."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import sqlalchemy as sa

from typer import config
from typer.betting.core import devig
from typer.learn import settle
from typer.learn.champion import current
from typer.pipeline.backtest import run_evaluate
from typer.store import db

LIVE_DIR = config.ROOT / "live"


def _window(engine: sa.Engine, since) -> dict:
    """Metryki okna z evaluate.py (na wyeksportowanych predykcjach championa)."""
    with tempfile.TemporaryDirectory() as td:
        csv, js = Path(td) / "preds.csv", Path(td) / "rep.json"
        df = settle.export_preds(engine, csv, role="champion", since=since)
        if df.empty or df["event_id"].nunique() < 1:
            return {}
        code, _ = run_evaluate(csv, json_out=js, by="sport,league,market")
        if not js.exists():
            return {}
        rep = json.loads(js.read_text())
    out = dict(n=rep.get("zdarzenia"), ll=rep.get("ll_model"), ece=rep.get("ece"), werdykt=rep.get("werdykt"),
               zaklady=rep.get("zaklady") or {}, dryf=rep.get("dryf") or {})
    if "odds_close" in df.columns and df["odds_close"].notna().any():
        lls = []
        for _, g in df[df["odds_close"].notna()].groupby(["event_id", "market"]):
            if len(g) > 1 and g["outcome"].sum() == 1:
                p = devig(g["odds_close"].to_numpy())
                lls.append(-np.log(p[g["outcome"].to_numpy() == 1][0]))
        out["ll_rynek"] = float(np.mean(lls)) if lls else None
    return out


def build(engine: sa.Engine, day=None) -> tuple[str, dict]:
    day = pd.Timestamp(day).date() if day else datetime.now(timezone.utc).date()
    lines = [f"TYPER  {day}"]
    payload: dict = dict(data=str(day), typy=[], wczoraj={}, okna={}, alarmy=[], wnioski=[])

    # --- typy na dzis: zaklady papierowe z dzisiejszych meczow ---
    bets = db.read_df(engine, """
        SELECT b.*, p.p_model, e.league, e.home, e.away, e.kickoff_utc FROM bets b
        JOIN predictions p ON p.id = b.prediction_id JOIN events e ON e.event_id = b.event_id""")
    lines.append("Typy na dziś")
    if len(bets):
        bets["kickoff_utc"] = pd.to_datetime(bets["kickoff_utc"], utc=True)
        today = bets[bets["kickoff_utc"].dt.date == day].sort_values("kickoff_utc")
        for r in today.itertuples(index=False):
            t = r.kickoff_utc.tz_convert(config.sports()["football"]["timezone"]).strftime("%H:%M")
            row = dict(godz=t, liga=r.league, mecz=f"{r.home} - {r.away}", rynek=r.market,
                       selekcja=r.selection, p=round(r.p_model, 3), kurs_fair=round(1 / r.p_model, 2),
                       kurs=r.odds, przewaga=round(r.edge, 4), stawka=round(r.stake_frac, 4))
            payload["typy"].append(row)
            lines.append(f"  {t} {r.league} {r.home} - {r.away} | {r.market} {r.selection} | p {r.p_model:.2f} | "
                         f"kurs fair {1 / r.p_model:.2f} | kurs {r.odds:.2f} | przewaga {r.edge:+.1%} | "
                         f"stawka {r.stake_frac:.1%}")
    if not payload["typy"]:
        lines.append("  brak zakładów z przewagą powyżej progu")

    # --- wczoraj ---
    y = day - timedelta(days=1)
    s = settle.settled(engine, role="champion")
    lines.append("Wczoraj")
    if len(s) and len(bets):
        s["kickoff_utc"] = pd.to_datetime(s["kickoff_utc"], utc=True)
        b = bets.merge(s[["prediction_id", "outcome"]], on="prediction_id")
        b = b[pd.to_datetime(b["kickoff_utc"], utc=True).dt.date == y]
        if len(b):
            prof = np.where(b["outcome"] == 1, b["stake_frac"] * (b["odds"] - 1), -b["stake_frac"])
            co = settle.closing_odds(engine)
            bc = b.merge(co, on=["event_id", "market", "selection"], how="left")
            clv = (bc["odds"] / bc["odds_close_fair"] - 1).dropna()
            payload["wczoraj"] = dict(typy=len(b), trafione=int(b["outcome"].sum()),
                                      clv=float(clv.mean()) if len(clv) else None,
                                      wynik_j=float(prof.sum() * 100))
            clv_txt = f"{clv.mean():+.1%}" if len(clv) else "brak kursów zamknięcia"
            lines.append(f"  {len(b)} typów, trafione {int(b['outcome'].sum())}, CLV śr. {clv_txt}, "
                         f"wynik {prof.sum() * 100:+.2f} j (1 j = 1% bankrolla)")
    if not payload["wczoraj"]:
        lines.append("  brak rozliczonych zakładów")

    # --- okna 30 / 90 dni ---
    lines.append("Okno 30 / 90 dni")
    for days in (30, 90):
        w = _window(engine, day - timedelta(days=days))
        payload["okna"][str(days)] = w
        if not w:
            lines.append(f"  {days} dni: brak rozliczonych predykcji")
            continue
        z = w["zaklady"]
        txt = f"  {days} dni: n {w['n']} | log loss {w['ll']:.3f}"
        txt += f" vs rynek {w['ll_rynek']:.3f}" if w.get("ll_rynek") else " vs rynek (brak kursów zamknięcia)"
        txt += f" | ECE {w['ece']:.3f}"
        if z.get("clv_sr") is not None:
            txt += f" | CLV {z['clv_sr']:+.1%} [{z['clv_ci90'][0]:+.1%}, {z['clv_ci90'][1]:+.1%}]"
        if z.get("roi") is not None:
            txt += f" | ROI {z['roi']:+.1%} [{z['roi_ci90'][0]:+.1%}, {z['roi_ci90'][1]:+.1%}]"
        lines.append(txt)

    # --- alarmy: dryf (od daty wdrozenia championa), zrodla danych ---
    lines.append("Alarmy")
    champ = current(engine)
    ref = champ.get("drift_reference_date") if champ else None
    if ref:
        w = _window(engine, pd.Timestamp(ref).date())
        for seg, hits in (w.get("dryf") or {}).items():
            payload["alarmy"].append(f"dryf {seg}: {len(hits)} alarm(y), ostatni {hits[-1]}")
    alerts_file = LIVE_DIR / "alerts.json"
    if alerts_file.exists():
        for a in json.loads(alerts_file.read_text())[-5:]:
            payload["alarmy"].append(f"{a['ts']}: {a['msg']}")
    lines += [f"  {a}" for a in payload["alarmy"]] or ["  brak"]

    # --- wnioski z dziennika bledow ---
    lines.append("Wnioski")
    j = db.read_df(engine, "SELECT * FROM error_journal ORDER BY id DESC LIMIT 10")
    if len(j):
        j["created_utc"] = pd.to_datetime(j["created_utc"], utc=True)
        new = j[j["created_utc"] >= pd.Timestamp.now(tz="UTC") - timedelta(days=1)]
        for r in new.itertuples(index=False):
            ctx = r.context if isinstance(r.context, dict) else json.loads(r.context or "{}")
            txt = f"{ctx.get('mecz', r.event_id)} {r.market} {ctx.get('selekcja', '')} wynik {ctx.get('wynik', '?')}: " \
                  f"p={r.p_actual:.3f}, klasa {r.final_class or r.suggested_class}"
            payload["wnioski"].append(txt)
    lines += [f"  {w}" for w in payload["wnioski"]] or ["  brak nowych wpisów w dzienniku błędów"]
    return "\n".join(lines), payload


def send(text: str, payload: dict) -> str:
    """JSON na webhook n8n (N8N_WEBHOOK_URL), ktory formatuje wiadomosc na Telegram.
    Bez webhooka zapis do live/report_<data>.json."""
    LIVE_DIR.mkdir(exist_ok=True)
    body = dict(payload, tekst=text)
    path = LIVE_DIR / f"report_{payload['data']}.json"
    path.write_text(json.dumps(body, ensure_ascii=False, indent=1, default=str))
    url = config.env("N8N_WEBHOOK_URL")
    if not url:
        return f"zapisano {path} (brak N8N_WEBHOOK_URL)"
    r = requests.post(url, json=json.loads(json.dumps(body, default=str)), timeout=30)
    r.raise_for_status()
    return f"wyslano na webhook ({r.status_code}) i zapisano {path}"
