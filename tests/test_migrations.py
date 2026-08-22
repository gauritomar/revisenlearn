"""Migrations against databases that have content in them.

Every other test in this suite starts from an empty database, which is how
the notes-first rework reached a real machine with two faults it could not
have hit here:

  * the batch rebuild of `notes` runs `DROP TABLE notes`, which fails with
    "FOREIGN KEY constraint failed" the moment anything references it — and
    nothing references an empty database's notes;
  * pysqlite never opens a transaction for DDL, so that failure committed
    everything before it and left `alembic_version` on the old revision.

Both are fixed in `migrations/env.py`. These tests are the ones that would
have caught them.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The revision immediately before the notes-first rework.
BEFORE = "17da8cdf5990"

#: Read from Alembic rather than pinned: the next migration to be written
#: should not fail these tests for the crime of existing.
def _head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(REPO_ROOT / "alembic.ini")))
    heads = script.get_heads()
    assert len(heads) == 1, f"expected a single head, got {heads}"
    return heads[0]


HEAD = _head()


def _alembic(db: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "RNL_DB_PATH": str(db)},
        capture_output=True, text=True,
    )


def _query(db: Path, sql: str, params: tuple = ()):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _version(db: Path) -> str:
    return _query(db, "SELECT version_num FROM alembic_version")[0][0]


def _tables(db: Path) -> set[str]:
    return {r[0] for r in _query(db, "SELECT name FROM sqlite_master WHERE type='table'")}


@pytest.fixture
def populated(tmp_path: Path) -> Path:
    """A database at the pre-rework revision, with a note the user wrote."""
    db = tmp_path / "populated.db"
    result = _alembic(db, "upgrade", BEFORE)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db)
    conn.executescript("""
        INSERT INTO subjects (id, name, sort_order, created_at)
            VALUES (1, 'GenAI', 0, '2026-08-01');
        INSERT INTO topics (id, subject_id, name, sort_order, created_at)
            VALUES (1, 1, 'Retrieval', 0, '2026-08-01');
        INSERT INTO subtopics (id, topic_id, name, sort_order, created_at)
            VALUES (1, 1, 'Hybrid search', 0, '2026-08-01');
        INSERT INTO notes (id, title, study_date, subject_id, topic_id,
                           subtopic_id, created_at, updated_at)
            VALUES (1, 'Hybrid search', '2026-08-01', 1, 1, 1,
                    '2026-08-01', '2026-08-01');
        INSERT INTO note_blocks (id, note_id, position, block_type, text,
                                 content_hash, created_at, updated_at)
            VALUES (1, 1, 0, 'paragraph', 'BM25 catches rare exact terms',
                    'abc123', '2026-08-01', '2026-08-01');
        INSERT INTO lessons (id, topic_id, subtopic_id, name, status, position,
                             created_at, updated_at)
            VALUES (1, 1, 1, 'Fixed vs semantic chunking', 'not_started', 0,
                    '2026-08-01', '2026-08-01');
        INSERT INTO lesson_items (id, lesson_id, title, done, position,
                                  created_at, updated_at)
            VALUES (1, 1, 'Read the chunking paper', 0, 0,
                    '2026-08-01', '2026-08-01');
    """)
    conn.commit()
    conn.close()
    return db


def test_a_database_with_notes_in_it_migrates_to_head(populated: Path) -> None:
    """The case the empty-database tests could not reach: `notes` is
    referenced by `note_blocks`, so rebuilding it needs enforcement off."""
    result = _alembic(populated, "upgrade", "head")
    assert result.returncode == 0, result.stderr

    assert _version(populated) == HEAD
    # The note the user wrote survives untouched. A second one appears: §2
    # converts the lesson's items onto "that lesson's note (creating the note
    # first if needed)", and this lesson had none.
    assert _query(populated, "SELECT count(*) FROM notes")[0][0] == 2
    assert _query(populated, "SELECT text FROM note_blocks ORDER BY id")[0][0] == \
        "BM25 catches rare exact terms"
    assert _query(populated,
                  "SELECT title, lesson_id FROM notes WHERE lesson_id IS NOT NULL") == \
        [("Fixed vs semantic chunking", 1)]
    # The new columns arrived, and nothing dangles.
    assert any(r[1] == "lesson_id" for r in _query(populated, "PRAGMA table_info(notes)"))
    assert _query(populated, "PRAGMA foreign_key_check") == []


def test_lesson_items_become_checklist_items_on_the_lessons_note(
        populated: Path) -> None:
    """Addendum §2 — "convert each into a `checklist_item` block appended to
    that lesson's note (creating the note first if needed)"."""
    result = _alembic(populated, "upgrade", "head")
    assert result.returncode == 0, result.stderr

    rows = _query(populated, "SELECT text, checked, lesson_id FROM checklist_items")
    assert rows == [("Read the chunking paper", 0, 1)]
    # …and the item exists as a real block, which is where it now lives.
    blocks = _query(populated,
                    "SELECT block_type, text FROM note_blocks "
                    "WHERE block_type = 'checklist_item'")
    assert blocks == [("checklist_item", "- [ ] Read the chunking paper")]
    assert "lesson_items" not in _tables(populated)


def test_a_failed_migration_leaves_the_database_untouched(
        populated: Path, tmp_path: Path) -> None:
    """pysqlite does not begin a transaction for DDL on its own, so without
    the wiring in env.py a failure commits everything before it. That is how a
    real database ended up half-migrated, with `alembic_version` still
    claiming the old revision."""
    migration = (REPO_ROOT / "migrations" / "versions"
                 / "06e630770a79_notes_first_rework_checklist_items_.py")
    original = migration.read_text()
    sabotaged = original.replace(
        "    if not _has_column('notes', 'lesson_id'):",
        "    raise RuntimeError('deliberate failure')\n\n"
        "    if not _has_column('notes', 'lesson_id'):",
        1,
    )
    assert sabotaged != original, "the injection point moved"

    migration.write_text(sabotaged)
    try:
        result = _alembic(populated, "upgrade", "head")
    finally:
        migration.write_text(original)

    assert result.returncode != 0
    assert "deliberate failure" in result.stderr

    # Nothing of the migration survived: not the new table, not the drop.
    assert _version(populated) == BEFORE
    tables = _tables(populated)
    assert "checklist_items" not in tables
    assert "lesson_items" in tables
    assert not any(t.startswith("_alembic_tmp") for t in tables)
    assert _query(populated, "SELECT count(*) FROM note_blocks")[0][0] == 1


def test_a_half_applied_database_can_still_reach_head(populated: Path) -> None:
    """The state one machine was actually left in: `checklist_items` created,
    `lesson_items` dropped, the columns never added, and an
    `_alembic_tmp_note_blocks` blocking every retry."""
    conn = sqlite3.connect(populated)
    conn.executescript("""
        CREATE TABLE checklist_items (
            id INTEGER NOT NULL PRIMARY KEY, note_block_id INTEGER NOT NULL,
            note_id INTEGER NOT NULL, lesson_id INTEGER,
            parent_checklist_item_id INTEGER, text VARCHAR NOT NULL,
            url VARCHAR, checked BOOLEAN NOT NULL, completed_at DATETIME,
            position INTEGER NOT NULL, created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT uq_checklist_note_block UNIQUE (note_block_id));
        DROP TABLE lesson_items;
        CREATE TABLE _alembic_tmp_note_blocks (id INTEGER PRIMARY KEY);
    """)
    conn.commit()
    conn.close()

    result = _alembic(populated, "upgrade", "head")
    assert result.returncode == 0, result.stderr

    assert _version(populated) == HEAD
    tables = _tables(populated)
    assert not any(t.startswith("_alembic_tmp") for t in tables)
    assert _query(populated, "SELECT count(*) FROM notes")[0][0] == 1
    assert _query(populated, "PRAGMA foreign_key_check") == []
