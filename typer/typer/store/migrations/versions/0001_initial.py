"""Schemat poczatkowy: tabele minimum ze skilla + triggery append-only.

Revision ID: 0001
Revises:
Create Date: 2026-10-31
"""
from alembic import op

from typer.store import db

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    db.metadata.create_all(bind)
    for ddl in db._append_only_ddl(bind.dialect.name):
        op.execute(ddl)


def downgrade():
    db.metadata.drop_all(op.get_bind())
