"""Tabela absences (kontuzje i zawieszenia przed meczem, API-Football).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05
"""
from alembic import op

from typer.store import db

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    db.absences.create(op.get_bind(), checkfirst=True)


def downgrade():
    db.absences.drop(op.get_bind(), checkfirst=True)
