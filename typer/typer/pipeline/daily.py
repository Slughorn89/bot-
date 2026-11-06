"""Cykl dzienny (sekcja 9.1): fetch -> predict -> bets -> settle -> learn -> report.

Tryb odtworzeniowy (--as-of RRRR-MM-DD): udaje, ze dzis jest podany dzien. Historia = mecze
sprzed tego dnia, terminarz = mecze z tego dnia z kursami Bet365 sprzed meczu, a wyniki
"przychodza" dopiero przy settle. Sluzy do sprawdzenia calej petli na prawdziwych danych, gdy
zywe zrodla terminarza sa niedostepne. To nie jest paper trading na zywo.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import sqlalchemy as sa

from typer import config
from typer.betting.core import Limits, select_and_stake
from typer.ingest.base import SourceUnavailable
from typer.learn import journal, settle
from typer.learn.champion import current, register
from typer.pipeline import layers as L
from typer.pipeline.backtest import LAYER_SETS, params_from_config
from typer.features import real_xg
from typer.pipeline.data import load_matches
from typer.pipeline.engine import Engine
from typer.store import db

log = logging.getLogger("typer.daily")
LIVE_DIR = config.ROOT / "live"
ALERTS = LIVE_DIR / "alerts.json"


def model_cfg() -> dict:
    m = config.model_params()
    return dict(version=m.get("version", "op-dev"), layers=m.get("layers", "online+cal"),
                value_threshold=m.get("value_threshold", config.gates().get("value_threshold", 0.05)),
                kelly_fraction=m.get("kelly_fraction", 0.25), tax_rate=m.get("tax_rate", 0.0),
                bet_markets=m.get("bet_markets", ["1X2", "OU2.5"]))


def alert(msg: str) -> None:
    """Nieudane pobranie ma wyslac alarm zamiast milczec."""
    LIVE_DIR.mkdir(exist_ok=True)
    items = json.loads(ALERTS.read_text()) if ALERTS.exists() else []
    items.append(dict(ts=f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", msg=msg))
    ALERTS.write_text(json.dumps(items[-50:], ensure_ascii=False, indent=1))
    log.error("ALARM: %s", msg)


def _split_replay(df: pd.DataFrame, as_of) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = pd.Timestamp(as_of).date()
    past = df[df["date"] < d]
    fx = df[df["date"] == d].copy()
    fx[["fthg", "ftag", "hthg", "htag", "hs", "as_", "hst", "ast", "hr", "ar"]] = np.nan
    return past, fx


def fetch(engine: sa.Engine, as_of=None) -> dict:
    """Historia + terminarz do bazy. Zwraca liczby zapisanych rekordow."""
    db.init_db(engine)
    hist = load_matches(refresh=as_of is None)
    if as_of:
        past, fx = _split_replay(hist, as_of)
    else:
        past, fx = hist, pd.DataFrame()
        try:
            from typer.ingest import footballdata_uk
            fx = footballdata_uk.load_fixtures()
        except SourceUnavailable as e:
            alert(f"terminarz football-data.co.uk niedostepny: {e}. Alternatywa: The Odds API (ODDS_API_KEY)")
    stats = db.store_matches(engine, past)
    if len(fx):
        db.store_matches(engine, fx)
    both = pd.concat([past, fx]) if len(fx) else past
    teams = pd.concat([both[["sport", "league", "home"]].set_axis(["sport", "league", "name"], axis=1),
                       both[["sport", "league", "away"]].set_axis(["sport", "league", "name"], axis=1)])
    teams = teams.drop_duplicates("name", keep="last")
    db.upsert(engine, db.participants, teams.to_dict("records"), ["sport", "name"])
    stats["fixtures"] = len(fx)
    return stats


def _fixtures_from_db(engine: sa.Engine, day) -> pd.DataFrame:
    d0 = pd.Timestamp(day).tz_localize("UTC") if pd.Timestamp(day).tzinfo is None else pd.Timestamp(day)
    ev = db.read_df(engine, "SELECT * FROM events WHERE status = 'scheduled'")
    if ev.empty:
        return ev
    ev["kickoff_utc"] = pd.to_datetime(ev["kickoff_utc"], utc=True)
    ev = ev[(ev["kickoff_utc"] >= d0) & (ev["kickoff_utc"] < d0 + timedelta(days=3))]
    od = db.read_df(engine, "SELECT event_id, market, selection, price, snapshot_utc FROM odds_snapshots "
                            "WHERE kind IN ('prematch', 'taken')")
    od = od.sort_values("snapshot_utc").drop_duplicates(["event_id", "market", "selection"], keep="last")
    colmap = {("1X2", "1"): "odds_h", ("1X2", "X"): "odds_d", ("1X2", "2"): "odds_a",
              ("OU2.5", "over2.5"): "odds_o25", ("OU2.5", "under2.5"): "odds_u25"}
    od["col"] = [colmap.get((m, s)) for m, s in zip(od["market"], od["selection"])]
    wide = od.dropna(subset=["col"]).pivot_table(index="event_id", columns="col", values="price")
    ev = ev.join(wide, on="event_id")
    ev["date"] = ev["kickoff_utc"].dt.date
    from typer.ingest.schema import COLUMNS
    for c in COLUMNS:
        if c not in ev.columns:
            ev[c] = np.nan
    return ev[COLUMNS]


def snapshot_odds(engine: sa.Engine, now: datetime | None = None) -> dict:
    """Snapshoty kursow z The Odds API w budzecie (typer/ingest/budget.py): 'taken' raz na lige i dzien
    meczowy przed pierwszym typem, 'close' dla kazdej godziny startu w oknie 10 min przed meczem.
    Nazwy druzyn mapowane na kanoniczne; niepewne trafiaja do entity_map ('pending') i ich mecze sa
    pomijane (nie zgadujemy)."""
    from typer.entities.mapping import resolve_many
    from typer.ingest import odds_api
    from typer.ingest.budget import Ledger, plan_odds_snapshots
    now = now or datetime.now(timezone.utc)
    ev = db.read_df(engine, "SELECT event_id, league, home, away, kickoff_utc FROM events "
                            "WHERE status = 'scheduled'")
    if ev.empty:
        return dict(snapshots=0, pending=0, zapytania=0)
    ev["kickoff_utc"] = pd.to_datetime(ev["kickoff_utc"], utc=True)
    have = db.read_df(engine, "SELECT o.event_id, o.kind, o.snapshot_utc, e.league, e.kickoff_utc FROM odds_snapshots o "
                              "JOIN events e ON e.event_id = o.event_id WHERE o.source = 'the_odds_api'")
    done = set()
    if len(have):
        have["kickoff_utc"] = pd.to_datetime(have["kickoff_utc"], utc=True)
        have["snapshot_utc"] = pd.to_datetime(have["snapshot_utc"], utc=True)
        for r in have.itertuples(index=False):
            done.add((r.league, "close", str(r.kickoff_utc)) if r.kind == "close"
                     else (r.league, "taken", str(r.snapshot_utc.date())))
    ledger = Ledger()
    plans = plan_odds_snapshots(ev, now, done, ledger)
    manual = db.read_df(engine, "SELECT league, raw_name, canonical FROM entity_map "
                                "WHERE source = 'the_odds_api' AND status = 'manual'")
    leagues = config.leagues()
    rows, pending_total, calls = [], 0, 0
    for plan in plans:
        meta = leagues.get(plan.league, {})
        if not meta.get("odds_api"):
            continue
        lg = plan.league
        try:
            snap = odds_api.parse(odds_api.download(meta["odds_api"], markets=",".join(plan.markets), now=now,
                                                    ledger=ledger), lg, now)
            calls += 1
        except SourceUnavailable as e:
            alert(f"The Odds API ({lg}, {plan.kind}) niedostepne: {e}")
            continue
        if snap.empty:
            continue
        cands = sorted(set(ev.loc[ev["league"] == lg, "home"]) | set(ev.loc[ev["league"] == lg, "away"]))
        man = dict(manual.loc[manual["league"] == lg, ["raw_name", "canonical"]].to_numpy())
        mapping, pending = resolve_many(list(snap["home_raw"]) + list(snap["away_raw"]), cands, man)
        db.upsert(engine, db.entity_map,
                  [dict(source="the_odds_api", league=lg, raw_name=k, canonical=v, score=1.0, status="auto")
                   for k, v in mapping.items()] +
                  [dict(source="the_odds_api", league=lg, raw_name=m.raw, canonical=m.canonical,
                        score=m.score, status="pending") for m in pending],
                  ["source", "league", "raw_name"], update=False)
        pending_total += len(pending)
        snap["home"], snap["away"] = snap["home_raw"].map(mapping), snap["away_raw"].map(mapping)
        snap = snap.dropna(subset=["home", "away"])
        evl = ev[ev["league"] == lg]
        j = snap.merge(evl, on=["home", "away"], suffixes=("", "_ev"))
        j = j[(j["kickoff_utc"] - j["kickoff_utc_ev"]).abs() <= pd.Timedelta(hours=6)]
        for r in j.itertuples(index=False):
            if r.kind not in ("taken", "close"):
                continue
            rows.append(dict(event_id=r.event_id, source="the_odds_api", bookmaker=r.bookmaker,
                             market=r.market, selection=r.selection, price=r.price, kind=r.kind,
                             snapshot_utc=pd.Timestamp(r.snapshot_utc).to_pydatetime()))
    key = ("event_id", "source", "bookmaker", "market", "selection", "snapshot_utc")
    rows = list({tuple(r[k] for k in key): r for r in rows}.values())  # to samo zapytanie dwa razy = jeden wiersz
    db.upsert(engine, db.odds_snapshots, rows, list(key), update=False)
    if pending_total:
        alert(f"{pending_total} nazw druzyn czeka na reczne mapowanie (entity_map, status pending)")
    return dict(snapshots=len(rows), pending=pending_total, zapytania=calls,
                kredyty_w_miesiacu=ledger.used("the_odds_api", now))


def collect_lineups(engine: sa.Engine, now: datetime | None = None, lead_minutes: int = 75) -> dict:
    """Sklady i kontuzje z API-Football dla meczow startujacych w ciagu lead_minutes (sklady sa ok. 60 min
    przed meczem). Tylko zbieranie: model ich jeszcze nie uzywa (brak historii do walidacji)."""
    from typer.entities.mapping import resolve_many
    from typer.ingest import api_football as af
    now = now or datetime.now(timezone.utc)
    src = config.sources().get("api_football", {})
    ids = src.get("ligi", {})
    ev = db.read_df(engine, "SELECT event_id, league, season, home, away, kickoff_utc FROM events "
                            "WHERE status = 'scheduled'")
    if ev.empty:
        return dict(mecze=0, wiersze=0)
    ev["kickoff_utc"] = pd.to_datetime(ev["kickoff_utc"], utc=True)
    now_ts = pd.Timestamp(now)
    soon = ev[(ev["kickoff_utc"] > now_ts) & (ev["kickoff_utc"] <= now_ts + pd.Timedelta(minutes=lead_minutes))]
    have = db.read_df(engine, "SELECT DISTINCT event_id FROM lineups WHERE source = 'api_football' AND status = 'start'")
    soon = soon[~soon["event_id"].isin(set(have["event_id"]) if len(have) else set())]
    rows, n_matched = [], 0
    for (lg, day), g in soon.groupby(["league", soon["kickoff_utc"].dt.date]):
        if lg not in ids:
            continue
        season = int(str(g["season"].iloc[0])[:4])
        try:
            fx = af.parse_fixtures(af.download("/fixtures", dict(league=ids[lg], season=season, date=str(day)),
                                               now=now, max_age_hours=6, stamp=str(day)))
            inj = af.parse_injuries(af.download("/injuries", dict(league=ids[lg], season=season, date=str(day)),
                                                now=now, max_age_hours=6, stamp=str(day)))
        except SourceUnavailable as e:
            alert(f"API-Football ({lg} {day}) niedostepne: {e}")
            continue
        if fx.empty:
            continue
        cands = sorted(set(ev.loc[ev["league"] == lg, "home"]) | set(ev.loc[ev["league"] == lg, "away"]))
        mapping, pending = resolve_many(list(fx["home_raw"]) + list(fx["away_raw"]), cands)
        db.upsert(engine, db.entity_map, [dict(source="api_football", league=lg, raw_name=k, canonical=v, score=1.0,
                                               status="auto") for k, v in mapping.items()] +
                  [dict(source="api_football", league=lg, raw_name=m.raw, canonical=m.canonical, score=m.score,
                        status="pending") for m in pending], ["source", "league", "raw_name"], update=False)
        fx["home"], fx["away"] = fx["home_raw"].map(mapping), fx["away_raw"].map(mapping)
        j = g.merge(fx.dropna(subset=["home", "away"]), on=["home", "away"], suffixes=("", "_af"))
        j = j[(j["kickoff_utc"] - j["kickoff_utc_af"]).abs() <= pd.Timedelta(hours=3)]
        for r in j.itertuples(index=False):
            try:
                lu = af.parse_lineups(af.download("/fixtures/lineups", dict(fixture=int(r.fixture_id)), now=now))
            except (SourceUnavailable, ValueError) as e:
                alert(f"API-Football sklady {r.event_id}: {e}")
                continue
            n_matched += 1
            part = pd.concat([lu, inj[inj["fixture_id"] == r.fixture_id].drop(columns="fixture_id")]) if len(inj) else lu
            for x in part.itertuples(index=False):
                team = mapping.get(x.team_raw)
                if team is None:
                    continue
                rows.append(dict(event_id=r.event_id, team=team, player=x.player, is_starter=bool(x.is_starter),
                                 position=x.position, status=x.status, reason=x.reason,
                                 published_utc=now, source="api_football"))
    db.upsert(engine, db.lineups, rows, ["event_id", "team", "player", "status", "source"], update=False)
    return dict(mecze=n_matched, wiersze=len(rows))


def variants() -> list[dict]:
    """Champion + challengerzy z config/model.yaml. Challenger typuje w cieniu (role=challenger),
    na tych samych meczach, i nie stawia zakladow (sekcja 9.5)."""
    m = config.model_params()
    out = [dict(version=m.get("version", "op-dev"), layers=m.get("layers", "online+cal"), role="champion",
                params=None, changes="champion")]
    for c in m.get("challengers", []) or []:
        out.append(dict(version=c["version"], layers=c.get("layers", out[0]["layers"]), role="challenger",
                        params=c.get("online_poisson"), changes=c.get("changes", ""),
                        real_xg=bool(c.get("real_xg", False))))
    return out


def _params_for(v: dict):
    base = params_from_config()
    if not v.get("params"):
        return base
    from dataclasses import replace
    return replace(base, **v["params"])


def predict(engine: sa.Engine, as_of=None, role: str | None = None, lead_minutes: int | None = None
            ) -> pd.DataFrame:
    """Predykcje dla terminarza: champion i challengerzy. Dopisywane, nigdy nadpisywane.
    lead_minutes: na zywo typujemy tylko mecze startujace w ciagu N minut (po skladach, 60-90 min
    przed meczem). Bez tego: wszystkie mecze z dnia as_of / najblizszych 3 dni.
    role: ogranicz do jednej roli (champion albo challenger); domyslnie obie."""
    today = pd.Timestamp(as_of).date() if as_of else datetime.now(timezone.utc).date()
    vs = [v for v in variants() if role is None or v["role"] == role]
    registry = db.read_df(engine, "SELECT version FROM model_registry")
    known = set(registry["version"]) if len(registry) else set()
    for v in vs:
        if v["version"] not in known:
            register(engine, v["version"], v["role"], _params_for(v).to_dict(),
                     "pierwsze wdrozenie" if v["role"] == "champion" else v["changes"],
                     drift_reference_date=str(today))
    hist = load_matches()
    past = hist[hist["date"] < today]
    fx = _fixtures_from_db(engine, today)
    if lead_minutes is not None and not as_of and len(fx):
        now_ts = pd.Timestamp.now(tz="UTC")
        ko = pd.to_datetime(fx["kickoff_utc"], utc=True)
        fx = fx[(ko > now_ts) & (ko <= now_ts + pd.Timedelta(minutes=lead_minutes))]
    elif as_of and len(fx):
        fx = fx[fx["date"] == today]
    if fx.empty:
        log.info("brak meczow w terminarzu")
        return pd.DataFrame()
    now = datetime.now(timezone.utc)
    frames: dict = {}
    out = []
    for v in vs:
        pkey = str(v.get("params")) + str(v.get("real_xg", False))
        if pkey not in frames:  # jeden przebieg ocen online na zestaw parametrow
            eng = Engine(_params_for(v), cutoff_mode="day", collect_features=True)
            hist_v = real_xg.attach(past)[0] if v.get("real_xg") else past   # xG tylko meczow rozegranych
            frame = eng.run(hist_v, predict_from="2008-07-01", fixtures=fx)
            frames[pkey] = (eng, frame)
        eng, frame = frames[pkey]
        tgt = frame[frame["fthg"].isna()]
        past_fr = frame[frame["fthg"].notna()]
        _audit(engine, eng, tgt, v["version"], now)
        tgt = L.live_apply(past_fr, tgt, LAYER_SETS[v["layers"]])
        out.append(_write_predictions(engine, tgt, v["version"], v["role"], now, as_of))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _audit(engine, eng, tgt, version, now) -> None:
    """Audyt: cechy "as of" kazdego typowanego meczu i stan ocen w chwili typu."""
    feat_cols = [c for c in L.FEATURES if c in tgt.columns]
    db.upsert(engine, db.features, [dict(event_id=r["event_id"], model_version=version, as_of_utc=now,
                                         values={c: float(r[c]) for c in feat_cols})
                                    for r in tgt.to_dict("records")], ["event_id", "model_version"], update=False)
    snap = []
    for lg in tgt["league"].unique():
        for t in eng.model.snapshot(lg):
            snap.append(dict(model_version=version, league=lg, team=t["team"], as_of_utc=now,
                             attack=t["attack"], defense=t["defense"],
                             extra=dict(n=t["n"], home_adv=eng.model.home[lg], mu=eng.model.mu[lg])))
    db.append(engine, db.ratings_history, snap)


def _write_predictions(engine, tgt, version, role, now, as_of) -> pd.DataFrame:
    existing = db.read_df(engine, "SELECT event_id, market, selection FROM predictions "
                                  "WHERE model_version = :v AND role = :r", v=version, r=role)
    have = set(map(tuple, existing.to_numpy())) if len(existing) else set()
    rows = []
    for r in tgt.itertuples(index=False):
        p1 = np.array([r.p_h, r.p_d, r.p_a]) / (r.p_h + r.p_d + r.p_a)
        sels = [("1X2", "1", p1[0], r.base_h, r.odds_h), ("1X2", "X", p1[1], r.base_d, r.odds_d),
                ("1X2", "2", p1[2], r.base_a, r.odds_a),
                ("OU2.5", "over2.5", r.p_over, r.base_over, r.odds_o25),
                ("OU2.5", "under2.5", 1 - r.p_over, 1 - r.base_over, r.odds_u25),
                ("BTTS", "yes", r.p_btts, r.base_btts, np.nan),
                ("BTTS", "no", 1 - r.p_btts, 1 - r.base_btts, np.nan)]
        for mkt, sel, p, b, o in sels:
            if (r.event_id, mkt, sel) in have:
                continue
            rows.append(dict(event_id=r.event_id, market=mkt, selection=sel, p_model=float(p),
                             p_baseline=float(b), model_version=version, role=role,
                             odds_taken=None if pd.isna(o) else float(o),
                             odds_source="b365_prematch" if as_of else "fixtures",
                             predicted_utc=now, kickoff_utc=pd.Timestamp(r.kickoff_utc).to_pydatetime()))
    ids = db.append(engine, db.predictions, rows)
    for r, i in zip(rows, ids):
        r["id"] = i
    return pd.DataFrame(rows)


def bankroll_state(engine: sa.Engine) -> tuple[float, float]:
    """Bankroll (1.0 = start) i jego szczyt, z rozliczonych zakladow papierowych."""
    b = db.read_df(engine, "SELECT b.stake_frac, b.odds, b.market, b.selection, r.fthg, r.ftag, b.placed_utc "
                           "FROM bets b JOIN results r ON r.event_id = b.event_id ORDER BY b.placed_utc")
    bank, peak = 1.0, 1.0
    for x in b.itertuples(index=False):
        o = settle.outcome(x.market, x.selection, int(x.fthg), int(x.ftag))
        if o is None:
            continue
        bank += x.stake_frac * (x.odds - 1) if o == 1 else -x.stake_frac
        peak = max(peak, bank)
    return bank, peak


def place_bets(engine: sa.Engine, preds: pd.DataFrame) -> pd.DataFrame:
    cfg = model_cfg()
    if preds.empty:
        return preds
    if "role" in preds.columns:
        preds = preds[preds["role"] == "champion"]  # challenger typuje w cieniu, nie gra
    c = preds[preds["odds_taken"].notna() & preds["market"].isin(cfg["bet_markets"])]
    cands = [dict(prediction_id=int(r.id), event_id=r.event_id, market=r.market, selection=r.selection,
                  p=r.p_model, odds=r.odds_taken) for r in c.itertuples(index=False)]
    bank, peak = bankroll_state(engine)
    chosen = select_and_stake(cands, Limits(), cfg["kelly_fraction"], cfg["value_threshold"],
                              cfg["tax_rate"], bankroll=bank, peak=peak)
    if not chosen and cands and peak > 0 and (peak - bank) / peak >= Limits().drawdown_stop:
        alert(f"STOP: bankroll {bank:.3f} spadl o >= 25% od szczytu {peak:.3f}. Pauza i audyt (sekcja 9.4).")
    rows = [dict(prediction_id=x["prediction_id"], event_id=x["event_id"], market=x["market"],
                 selection=x["selection"], odds=x["odds"], edge=x["edge"], stake_frac=x["stake_frac"],
                 paper=True) for x in chosen]
    db.append(engine, db.bets, rows)
    return pd.DataFrame(rows)


def settle_day(engine: sa.Engine, as_of=None) -> dict:
    """Wyniki do bazy (w trybie odtworzeniowym: wyniki meczow z dnia as_of), dziennik bledow."""
    if as_of:
        hist = load_matches()
        day = hist[hist["date"] == pd.Timestamp(as_of).date()]
        db.store_matches(engine, day)
    else:
        db.store_matches(engine, load_matches(refresh=True))
    s = settle.settled(engine, role=None)
    n_j = journal.update_journal(engine, s[s["role"] == "champion"]) if len(s) else 0
    n_clv = settle.record_clv(engine)
    return dict(settled=int(s["event_id"].nunique()) if len(s) else 0, journal=n_j, clv=n_clv)
