"""Engine, pragmas, session factory and the single application write lock.

Spec §6 **[LOCKED]**: WAL, ``busy_timeout=5000``, ``foreign_keys=ON``. All
writes go through one ``Session`` factory with a short-lived transaction, and
the (future) pipeline worker thread takes an application-level ``threading.Lock``
around its transactions. One connection pool, never two.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from . import config

#: Taken by any background writer (pipeline worker, backup) around its
#: transaction. Request handlers are already serialised by SQLite's single
#: writer, but the worker holds longer transactions and must not interleave.
write_lock = threading.Lock()

_engine: Engine | None = None
_engine_url: str | None = None


def _apply_pragmas(dbapi_connection, _connection_record) -> None:
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def get_engine() -> Engine:
    """Process-wide singleton engine. Rebuilt if the configured URL changes,
    which only happens in tests."""
    global _engine, _engine_url
    url = config.database_url()
    if _engine is not None and _engine_url == url:
        return _engine
    if _engine is not None:
        _engine.dispose()
    engine = create_engine(
        url,
        echo=False,
        # SQLite + a threaded worker in the same process.
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", _apply_pragmas)
    _engine = engine
    _engine_url = url
    return engine


def reset_engine() -> None:
    """Drop the cached engine. Used by tests between scratch databases."""
    global _engine, _engine_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _engine_url = None


@contextmanager
def session_scope() -> Iterator[Session]:
    """Short-lived transaction. Commits on success, rolls back on error."""
    session = Session(get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session


# --------------------------------------------------------------------------
# FTS5 (spec §6: virtual table over note_blocks.text and concepts)
# --------------------------------------------------------------------------

FTS_NOTE_BLOCKS_DDL = [
    # `content=''` — a contentless external-content-free index. We own the
    # rowid mapping explicitly, which keeps rebuild logic simple and avoids
    # SQLModel and FTS5 fighting over the same table.
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS note_blocks_fts USING fts5(
        text,
        note_id UNINDEXED,
        note_block_id UNINDEXED,
        tokenize = 'porter unicode61'
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS concepts_fts USING fts5(
        canonical_name,
        definition,
        concept_id UNINDEXED,
        tokenize = 'porter unicode61'
    )
    """,
]


def create_fts_tables(connection) -> None:
    for ddl in FTS_NOTE_BLOCKS_DDL:
        connection.execute(text(ddl))


def reindex_block(session: Session, block) -> None:
    """Keep the FTS index in step with one note block.

    Called on every block write. Deletes any existing row for the block then
    re-inserts, so it is safe for both create and update.
    """
    session.exec(
        text("DELETE FROM note_blocks_fts WHERE note_block_id = :bid").bindparams(
            bid=block.id
        )
    )
    if block.deleted_at is None and (block.text or "").strip():
        session.exec(
            text(
                "INSERT INTO note_blocks_fts (text, note_id, note_block_id) "
                "VALUES (:text, :note_id, :bid)"
            ).bindparams(text=block.text, note_id=block.note_id, bid=block.id)
        )
