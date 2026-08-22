"""Alembic environment.

The database URL always comes from ``revisenlearn.config`` so that ``alembic``
on the command line and the app in-process agree, including under the test
suite's ``RNL_DB_PATH`` override.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool
from sqlmodel import SQLModel

from revisenlearn import config as app_config
from revisenlearn import models  # noqa: F401  (registers every table)

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

alembic_config.set_main_option("sqlalchemy.url", app_config.database_url())

target_metadata = SQLModel.metadata


def _apply_pragmas(dbapi_connection, _connection_record) -> None:
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def run_migrations_offline() -> None:
    context.configure(
        url=app_config.database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # Spec §6 [LOCKED]. journal_mode=WAL is a persistent property of the
    # database file, so applying it here means a freshly migrated database is
    # already in WAL before the app ever opens it.
    #
    # These must run on the raw DBAPI connection at connect time, NOT inside
    # the migration transaction: SQLite refuses to change journal_mode from
    # within a transaction, and issuing it on the SQLAlchemy connection
    # autobegins one that then swallows Alembic's version-table write.
    event.listen(connectable, "connect", _apply_pragmas)

    with connectable.connect() as connection:
        # SQLite needs batch mode for most ALTERs.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
