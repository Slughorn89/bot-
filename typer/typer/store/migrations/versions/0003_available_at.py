"""Warstwa danych (modul 1): available_at/fetched_at w tabelach kuratorowanych, audyt pobran,
stadiony i tabele rekordow (statystyki, sedziowie, pogoda, gielda, wiadomosci, tenis).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05
"""
import sqlalchemy as sa
from alembic import op

from typer.store import db

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TIMESTAMPED = ("events", "results", "odds_snapshots", "lineups")


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for t in TIMESTAMPED:
        cols = {c["name"] for c in insp.get_columns(t)}
        with op.batch_alter_table(t) as b:
            for c in ("available_at", "fetched_at"):
                if c not in cols:
                    b.add_column(sa.Column(c, sa.DateTime(timezone=True)))
    new = [db.raw_fetches, db.venues, *db.RECORD_TABLES.values()]
    db.metadata.create_all(bind, tables=new, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    db.metadata.drop_all(bind, tables=[db.raw_fetches, db.venues, *db.RECORD_TABLES.values()])
    for t in TIMESTAMPED:
        with op.batch_alter_table(t) as b:
            b.drop_column("fetched_at")
            b.drop_column("available_at")
