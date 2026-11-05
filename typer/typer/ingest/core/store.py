"""Zapis rekordow do bazy (idempotentnie po source_key) i audytu pobran (raw_fetches)."""
from __future__ import annotations

from collections import defaultdict

import sqlalchemy as sa

from typer.ingest.core.records import BaseRecord
from typer.store import db


def store_records(engine: sa.Engine, records: list[BaseRecord]) -> dict[str, int]:
    """Rekordy -> tabele (typ rekordu = tabela). Ponowny zapis tego samego source_key aktualizuje wiersz."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[r.record_type].append(r.model_dump())
    out = {}
    for name, rows in groups.items():
        rows = list({row["source_key"]: row for row in rows}.values())
        db.upsert(engine, db.RECORD_TABLES[name], rows, ["source_key"])
        out[name] = len(rows)
    return out


def store_audit(engine: sa.Engine, audit: list[dict]) -> int:
    if audit:
        db.append(engine, db.raw_fetches, audit)
    return len(audit)
