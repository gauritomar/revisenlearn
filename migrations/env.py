"""Alembic environment.

The database URL always comes from ``revisenlearn.config`` so that ``alembic``
on the command line and the app in-process agree, including under the test
suite's ``RNL_DB_PATH`` override.
"""

from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool
from sqlmodel import SQLModel

from revisenlearn import config as app_config
from revisenlearn import models  # noqa: F401  (registers every table)

log = logging.getLogger("alembic.env")

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

alembic_config.set_main_option("sqlalchemy.url", app_config.database_url())

target_metadata = SQLModel.metadata


#: FTS5 virtual tables and the shadow tables SQLite creates alongside them
#: (`*_content`, `*_data`, `*_idx`, `*_docsize`, `*_config`) are managed by
#: hand in their own migration, not by SQLModel's metadata. Without this filter
#: autogenerate sees them as orphans and emits DROP TABLE for every one.
_FTS_PREFIXES = ("note_blocks_fts", "concepts_fts")


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and any(name.startswith(p) for p in _FTS_PREFIXES):
        return False
    return True


def _apply_pragmas(dbapi_connection, _connection_record) -> None:
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    # Foreign keys stay OFF *for migrations only*. SQLite cannot ALTER most
    # things, so Alembic's batch mode rebuilds a table: copy into
    # `_alembic_tmp_x`, DROP the original, rename. With enforcement on, that
    # DROP fails the moment anything references the table —
    #     DROP TABLE notes -> FOREIGN KEY constraint failed
    # because note_blocks, checklist_items and concept_sources all point at
    # it. This is the documented approach for SQLite batch migrations, and it
    # is safe: the rebuild puts every row back under the same ids, and
    # `PRAGMA foreign_key_check` below proves it before the transaction ends.
    #
    # Runtime connections are unaffected — db.py turns enforcement on for
    # every connection the app itself opens (spec §6 [LOCKED]).
    cur.execute("PRAGMA foreign_keys=OFF")
    cur.close()
    # pysqlite emits BEGIN only before INSERT/UPDATE/DELETE — never before
    # DDL. Left alone, every CREATE/DROP/ALTER in a migration commits the
    # moment it runs, so a failure halfway through leaves a half-migrated
    # database whose `alembic_version` still claims the old revision. That is
    # exactly how this repo's live database ended up with a `checklist_items`
    # table, no `lesson_items`, and a leftover `_alembic_tmp_note_blocks`.
    #
    # Setting isolation_level to None stops pysqlite managing transactions at
    # all; the "begin" handler below then issues a real BEGIN, which SQLite
    # *does* roll back over DDL.
    dbapi_connection.isolation_level = None


def _begin(conn) -> None:
    conn.exec_driver_sql("BEGIN")


def _drop_interrupted_batch_tables(connection) -> None:
    """Remove `_alembic_tmp_*` tables left by an interrupted batch ALTER.

    Alembic's SQLite batch mode rebuilds a table by copying it into
    `_alembic_tmp_<name>` and renaming. If that is interrupted, the tmp table
    survives and every later attempt fails with "table _alembic_tmp_x already
    exists" — a wall the user cannot get past without hand-editing their own
    database. The leftover holds no data anyone can reach, so it goes.
    """
    from sqlalchemy import text

    rows = connection.execute(text(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name LIKE '_alembic_tmp_%'"
    )).fetchall()
    for (name,) in rows:
        log.warning("Dropping %s, left by an interrupted migration", name)
        connection.execute(text(f'DROP TABLE "{name}"'))


def _assert_referential_integrity(connection) -> None:
    """Fail the migration if a rebuild left a dangling reference.

    Enforcement is off while tables are rebuilt, so this is the check that
    would otherwise have been happening statement by statement. It runs inside
    the same transaction: a violation rolls the whole migration back rather
    than leaving a quietly broken database.
    """
    from sqlalchemy import text

    violations = connection.execute(text("PRAGMA foreign_key_check")).fetchall()
    if violations:
        sample = ", ".join(f"{v[0]}(rowid={v[1]}) -> {v[2]}" for v in violations[:5])
        raise RuntimeError(
            f"Migration left {len(violations)} dangling foreign key(s): {sample}"
        )


def run_migrations_offline() -> None:
    context.configure(
        url=app_config.database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        include_object=include_object,
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
    event.listen(connectable, "begin", _begin)

    with connectable.connect() as connection:
        _drop_interrupted_batch_tables(connection)

        # SQLite needs batch mode for most ALTERs.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
            _assert_referential_integrity(connection)

        # Alembic treats SQLite as non-transactional DDL and so does not
        # commit for us; with pysqlite's own transaction handling disabled
        # above, nothing else will either, and closing the connection would
        # roll the entire migration back — silently, with exit code 0.
        connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
