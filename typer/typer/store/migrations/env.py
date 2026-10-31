"""Alembic: migracje schematu. URL z DATABASE_URL, metadane z typer.store.db."""
from alembic import context

from typer import config
from typer.store.db import get_engine, metadata

target_metadata = metadata


def run_migrations_offline():
    context.configure(url=config.database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = get_engine()
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
