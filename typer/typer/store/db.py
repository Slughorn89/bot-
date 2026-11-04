"""Schemat bazy (SQLAlchemy Core). Dziala na PostgreSQL (produkcja) i SQLite (prototyp, testy).

Zasady:
  * predictions i bets sa tylko do dopisywania: UPDATE/DELETE blokuja triggery w bazie,
    nie tylko kod aplikacji. Bez tego nie da sie uczciwie ocenic modelu.
  * kazdy rekord ma znaczniki czasu UTC.
  * zapisy idempotentne: upsert po kluczu zrodla.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import sqlalchemy as sa
from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, Integer, MetaData, String, Table,
                        Text, UniqueConstraint, event)

from typer import config
from typer.features.asof import collection_time

metadata = MetaData()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


events = Table(
    "events", metadata,
    Column("event_id", String(160), primary_key=True),
    Column("sport", String(20), nullable=False),
    Column("league", String(10), nullable=False, index=True),
    Column("season", String(10)),
    Column("kickoff_utc", DateTime(timezone=True), nullable=False, index=True),
    Column("time_known", Boolean, default=True),
    Column("home", String(80), nullable=False),
    Column("away", String(80), nullable=False),
    Column("status", String(12), default="scheduled"),  # scheduled | finished | postponed
    Column("source", String(60)),
    Column("first_seen_utc", DateTime(timezone=True), default=utcnow),
    Column("updated_utc", DateTime(timezone=True), default=utcnow, onupdate=utcnow),
)

participants = Table(
    "participants", metadata,
    Column("participant_id", Integer, primary_key=True, autoincrement=True),
    Column("sport", String(20), nullable=False),
    Column("league", String(10)),
    Column("name", String(80), nullable=False),
    UniqueConstraint("sport", "name", name="uq_participant"),
)

entity_map = Table(
    "entity_map", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source", String(40), nullable=False),
    Column("league", String(10), nullable=False),
    Column("raw_name", String(120), nullable=False),
    Column("canonical", String(80)),
    Column("score", Float),
    Column("status", String(12), nullable=False),  # manual | alias | auto | pending | rejected
    Column("created_utc", DateTime(timezone=True), default=utcnow),
    UniqueConstraint("source", "league", "raw_name", name="uq_entity"),
)

odds_snapshots = Table(
    "odds_snapshots", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String(160), nullable=False, index=True),
    Column("source", String(40), nullable=False),
    Column("bookmaker", String(40), nullable=False),
    Column("market", String(20), nullable=False),
    Column("selection", String(20), nullable=False),
    Column("price", Float, nullable=False),
    Column("kind", String(10), nullable=False),  # taken | close | prematch | bench
    Column("snapshot_utc", DateTime(timezone=True), nullable=False),
    UniqueConstraint("event_id", "source", "bookmaker", "market", "selection", "snapshot_utc",
                     name="uq_odds"),
)

lineups = Table(
    "lineups", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String(160), nullable=False, index=True),
    Column("team", String(80), nullable=False),
    Column("player", String(120), nullable=False),
    Column("is_starter", Boolean),
    Column("position", String(10)),
    Column("published_utc", DateTime(timezone=True)),
    Column("source", String(40)),
)

ratings_history = Table(
    "ratings_history", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("model_version", String(40), nullable=False),
    Column("league", String(10), nullable=False),
    Column("team", String(80), nullable=False),
    Column("as_of_utc", DateTime(timezone=True), nullable=False),
    Column("attack", Float),
    Column("defense", Float),
    Column("extra", JSON),
)

features = Table(
    "features", metadata,
    Column("event_id", String(160), primary_key=True),
    Column("model_version", String(40), primary_key=True),
    Column("as_of_utc", DateTime(timezone=True), nullable=False),
    Column("values", JSON, nullable=False),
)

predictions = Table(
    "predictions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String(160), nullable=False, index=True),
    Column("market", String(20), nullable=False),
    Column("selection", String(20), nullable=False),
    Column("p_model", Float, nullable=False),
    Column("p_baseline", Float),
    Column("model_version", String(40), nullable=False),
    Column("role", String(12), nullable=False, default="champion"),  # champion | challenger
    Column("odds_taken", Float),
    Column("odds_source", String(40)),
    Column("predicted_utc", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("kickoff_utc", DateTime(timezone=True), nullable=False),
)

bets = Table(
    "bets", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("prediction_id", Integer, nullable=False),
    Column("event_id", String(160), nullable=False, index=True),
    Column("market", String(20), nullable=False),
    Column("selection", String(20), nullable=False),
    Column("odds", Float, nullable=False),
    Column("edge", Float, nullable=False),
    Column("stake_frac", Float, nullable=False),  # ulamek bankrolla
    Column("paper", Boolean, nullable=False, default=True),
    Column("placed_utc", DateTime(timezone=True), nullable=False, default=utcnow),
)

results = Table(
    "results", metadata,
    Column("event_id", String(160), primary_key=True),
    Column("fthg", Integer, nullable=False),
    Column("ftag", Integer, nullable=False),
    Column("hthg", Integer),
    Column("htag", Integer),
    Column("hr", Integer),
    Column("ar", Integer),
    Column("source", String(60)),
    Column("settled_utc", DateTime(timezone=True), default=utcnow),
)

error_journal = Table(
    "error_journal", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("prediction_id", Integer, nullable=False),
    Column("event_id", String(160), nullable=False),
    Column("market", String(20), nullable=False),
    Column("p_actual", Float, nullable=False),     # p, jakie model dal faktycznemu wynikowi
    Column("log_loss", Float, nullable=False),
    Column("context", JSON),
    Column("suggested_class", String(16)),          # SZUM? | SLEPA_PLAMKA? (podpowiedz automatu)
    Column("final_class", String(16)),              # SZUM | SLEPA_PLAMKA (decyzja czlowieka)
    Column("note", Text),
    Column("created_utc", DateTime(timezone=True), default=utcnow),
    UniqueConstraint("prediction_id", name="uq_journal_pred"),
)

model_registry = Table(
    "model_registry", metadata,
    Column("version", String(40), primary_key=True),
    Column("created_utc", DateTime(timezone=True), default=utcnow),
    Column("role", String(12), nullable=False),  # champion | challenger | retired
    Column("params", JSON),
    Column("changes", Text),
    Column("validation", JSON),
    Column("drift_reference_date", String(10)),   # --since dla evaluate.py
)

APPEND_ONLY = ("predictions", "bets")


def _append_only_ddl(dialect: str) -> list[str]:
    out = []
    for t in APPEND_ONLY:
        if dialect == "sqlite":
            for op in ("UPDATE", "DELETE"):
                out.append(f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
                           f"BEGIN SELECT RAISE(ABORT, '{t} jest tylko do dopisywania'); END;")
        elif dialect == "postgresql":
            out.append(f"""
            CREATE OR REPLACE FUNCTION {t}_append_only() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION '{t} jest tylko do dopisywania'; END; $$ LANGUAGE plpgsql;""")
            out.append(f"DROP TRIGGER IF EXISTS {t}_no_change ON {t};")
            out.append(f"CREATE TRIGGER {t}_no_change BEFORE UPDATE OR DELETE ON {t} "
                       f"FOR EACH ROW EXECUTE FUNCTION {t}_append_only();")
    return out


def get_engine(url: str | None = None) -> sa.Engine:
    url = url or config.database_url()
    if url.startswith("sqlite:///"):
        from pathlib import Path
        Path(url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
    eng = sa.create_engine(url, future=True)
    if eng.dialect.name == "sqlite":
        @event.listens_for(eng, "connect")
        def _fk(dbapi_conn, _):  # pragma: no cover - trywialne
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
    return eng


def init_db(engine: sa.Engine) -> None:
    metadata.create_all(engine)
    with engine.begin() as c:
        for ddl in _append_only_ddl(engine.dialect.name):
            c.exec_driver_sql(ddl)


def _insert(engine):
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert


def upsert(engine: sa.Engine, table: Table, rows: list[dict], keys: list[str],
           update: bool = True) -> int:
    """Idempotentny zapis: konflikt po kluczu = aktualizacja (albo pominiecie, gdy update=False)."""
    if not rows:
        return 0
    insert = _insert(engine)
    cols = {c.name for c in table.columns}
    rows = [{k: _clean(v) for k, v in r.items() if k in cols} for r in rows]
    with engine.begin() as c:
        for i in range(0, len(rows), 500):
            stmt = insert(table).values(rows[i:i + 500])
            if update:
                upd = {k: stmt.excluded[k] for k in rows[0] if k not in keys}
                stmt = stmt.on_conflict_do_update(index_elements=keys, set_=upd) if upd \
                    else stmt.on_conflict_do_nothing(index_elements=keys)
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=keys)
            c.execute(stmt)
    return len(rows)


def append(engine: sa.Engine, table: Table, rows: list[dict]) -> list[int]:
    """Dopisanie (dla tabel append-only). Zwraca id nowych wierszy."""
    if not rows:
        return []
    cols = {c.name for c in table.columns}
    ids = []
    with engine.begin() as c:
        for r in rows:
            res = c.execute(table.insert().values({k: _clean(v) for k, v in r.items() if k in cols}))
            ids.append(res.inserted_primary_key[0])
    return ids


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and v != v:  # NaN
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if hasattr(v, "item"):  # typy numpy
        return v.item()
    return v


def read_df(engine: sa.Engine, sql: str, **params) -> pd.DataFrame:
    with engine.connect() as c:
        return pd.read_sql(sa.text(sql), c, params=params)


def store_matches(engine: sa.Engine, df: pd.DataFrame) -> dict:
    """Mecze ze wspolnego schematu -> events, results, odds_snapshots."""
    ev, res, odds = [], [], []
    for r in df.itertuples(index=False):
        played = pd.notna(r.fthg) and pd.notna(r.ftag)
        ev.append(dict(event_id=r.event_id, sport=r.sport, league=r.league, season=r.season,
                       kickoff_utc=pd.Timestamp(r.kickoff_utc).to_pydatetime(),
                       time_known=bool(r.time_known), home=r.home, away=r.away,
                       status="finished" if played else "scheduled", source=r.source))
        if played:
            res.append(dict(event_id=r.event_id, fthg=int(r.fthg), ftag=int(r.ftag),
                            hthg=None if pd.isna(r.hthg) else int(r.hthg),
                            htag=None if pd.isna(r.htag) else int(r.htag),
                            hr=None if pd.isna(r.hr) else int(r.hr),
                            ar=None if pd.isna(r.ar) else int(r.ar), source=r.source))
        ko = pd.Timestamp(r.kickoff_utc).to_pydatetime()
        snaps = {"prematch": collection_time(r.date), "close": ko, "bench": ko}
        for kind, prefix, book in (("prematch", "odds", "b365"), ("close", "close", "pinnacle"),
                                   ("bench", "bench", "unknown")):
            for mkt, sels in (("1X2", ("h", "d", "a")), ("OU2.5", ("o25", "u25"))):
                for s in sels:
                    col = f"{prefix}_{s}"
                    v = getattr(r, col, None)
                    if v is not None and pd.notna(v):
                        sel = {"h": "1", "d": "X", "a": "2", "o25": "over2.5", "u25": "under2.5"}[s]
                        odds.append(dict(event_id=r.event_id, source=r.source, bookmaker=book,
                                         market=mkt, selection=sel, price=float(v), kind=kind,
                                         snapshot_utc=snaps[kind]))
    upsert(engine, events, ev, ["event_id"])
    upsert(engine, results, res, ["event_id"])
    upsert(engine, odds_snapshots, odds,
           ["event_id", "source", "bookmaker", "market", "selection", "snapshot_utc"], update=False)
    return dict(events=len(ev), results=len(res), odds=len(odds))


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
