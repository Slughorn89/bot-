"""Modul 6: tabela bet_clv (CLV zakladu wzgledem zamkniecia ostrego bukmachera), tylko do dopisywania.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-05
"""
from alembic import op

from typer.store import db

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    db.metadata.create_all(bind, tables=[db.bet_clv], checkfirst=True)
    for ddl in db._append_only_ddl(bind.dialect.name):
        if "bet_clv" in ddl:
            op.execute(ddl)


def downgrade():
    db.metadata.drop_all(op.get_bind(), tables=[db.bet_clv])

