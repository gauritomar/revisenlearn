"""Clear authored content, keeping the schema (consolidated addendum §0).

    uv run python scripts/reset_content.py          # dry run, shows counts
    uv run python scripts/reset_content.py --yes    # back up, then clear

Deletes every row from the tables §0 names — subjects, topics, subtopics,
lessons, lesson_items, notes, note_blocks, resources — plus the join tables and
concept_sources that reference them, which would otherwise dangle.

Takes a `VACUUM INTO` snapshot first, per §17 of the main spec. Nothing else is
touched: `settings`, `concepts`, `review_items`, `review_logs`, `llm_runs` and
the rest survive.

This is deliberately a script rather than something the app can do to itself.
Wiping the user's notes is not a button anything should have.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from revisenlearn import config  # noqa: E402
from revisenlearn.backup import backup_now  # noqa: E402

#: Children before parents, so nothing dangles even mid-transaction.
CLEAR_ORDER = (
    "note_lesson_links",
    "note_resource_links",
    "lesson_resource_links",
    "concept_sources",
    "note_blocks",
    "notes",
    "lesson_items",
    "lessons",
    "resources",
    "subtopics",
    "topics",
    "subjects",
)

#: FTS5 indexes point at note_blocks rowids; stale entries would survive and
#: surface deleted text in ⌘K.
FTS_TABLES = ("note_blocks_fts", "concepts_fts")

KEPT = ("settings", "concepts", "review_items", "review_logs", "mcqs",
        "questions", "llm_runs", "pipeline_jobs", "todos")


def counts(conn: sqlite3.Connection, tables) -> dict[str, int]:
    out = {}
    for table in tables:
        try:
            out[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            pass
    return out


def main() -> int:
    confirmed = "--yes" in sys.argv
    db_path = config.db_path()

    if not db_path.exists():
        print(f"No database at {db_path}. Nothing to do.")
        return 0

    conn = sqlite3.connect(db_path)
    try:
        to_clear = counts(conn, CLEAR_ORDER)
        surviving = counts(conn, KEPT)
    finally:
        conn.close()

    print(f"Database: {db_path}\n")
    print("Would clear:")
    for table, n in to_clear.items():
        if n:
            print(f"  {table:24} {n}")
    if not any(to_clear.values()):
        print("  (already empty)")

    print("\nWould keep:")
    for table, n in surviving.items():
        if n:
            print(f"  {table:24} {n}")

    if not confirmed:
        print("\nDry run. Re-run with --yes to take a backup and clear.")
        return 0

    created, _ = backup_now()
    print(f"\nSnapshot taken: {created.path}")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        cleared = 0
        for table in CLEAR_ORDER:
            try:
                cleared += conn.execute(f"DELETE FROM {table}").rowcount or 0
            except sqlite3.OperationalError:
                continue
        for table in FTS_TABLES:
            try:
                conn.execute(f"DELETE FROM {table}")
            except sqlite3.OperationalError:
                continue
        conn.commit()
    finally:
        conn.close()

    print(f"Cleared {cleared} row(s). Schema and settings untouched.")
    print("Restore with: cp '%s' '%s'" % (created.path, db_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
