"""lineups: status zawodnika (start/lawka/kontuzja/zawieszenie), powod, unikalnosc wpisu.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("lineups")}
    with op.batch_alter_table("lineups") as b:
        if "status" not in cols:
            b.add_column(sa.Column("status", sa.String(20)))
        if "reason" not in cols:
            b.add_column(sa.Column("reason", sa.String(160)))
        uq = {u["name"] for u in sa.inspect(op.get_bind()).get_unique_constraints("lineups")}
        if "uq_lineup" not in uq:
            b.create_unique_constraint("uq_lineup", ["event_id", "team", "player", "status", "source"])


def downgrade():
    with op.batch_alter_table("lineups") as b:
        b.drop_constraint("uq_lineup", type_="unique")
        b.drop_column("reason")
        b.drop_column("status")
