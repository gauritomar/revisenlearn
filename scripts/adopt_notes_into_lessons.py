"""Give existing subtopic notes a Lesson to hang off (consolidated addendum §3).

    uv run python scripts/adopt_notes_into_lessons.py          # dry run
    uv run python scripts/adopt_notes_into_lessons.py --yes    # back up, then adopt

Before the rework, a note belonged to a Subtopic and the sidebar opened it by
clicking that subtopic. §5 made Subject/Topic/Subtopic names inert: the sidebar
now opens a **Lesson's** note. Notes written under the old model are therefore
still there — searchable, on the calendar, in exports — but nothing in the tree
opens them.

This creates one Lesson per orphaned note, named after the note, in the note's
own subtopic, and points the note at it. Nothing is deleted and no text is
touched; a note that already has a lesson is left alone.

Optional. If you are starting your structure from scratch (§0), skip it.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from revisenlearn import config  # noqa: E402
from revisenlearn.backup import backup_now  # noqa: E402

ORPHANS = """
    SELECT n.id, n.title, n.subtopic_id, n.topic_id, s.name
    FROM notes n
    LEFT JOIN subtopics s ON s.id = n.subtopic_id
    WHERE n.deleted_at IS NULL
      AND n.lesson_id IS NULL
      AND n.resource_id IS NULL
      AND n.subtopic_id IS NOT NULL
    ORDER BY n.id
"""


def main() -> int:
    confirmed = "--yes" in sys.argv
    db_path = config.db_path()
    if not db_path.exists():
        print(f"No database at {db_path}. Nothing to do.")
        return 0

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(ORPHANS).fetchall()
        if not rows:
            print("Every note already opens from the sidebar. Nothing to do.")
            return 0

        print(f"Database: {db_path}\n")
        print(f"{len(rows)} note(s) with no lesson:\n")
        for _id, title, _st, _t, subtopic in rows:
            print(f"  {title:32} under {subtopic}")

        if not confirmed:
            print("\nDry run. Re-run with --yes to take a backup and adopt them.")
            return 0

        created, _ = backup_now()
        print(f"\nSnapshot taken: {created.path}")

        now = datetime.now(timezone.utc).isoformat()
        adopted = 0
        for note_id, title, subtopic_id, topic_id, _subtopic in rows:
            position = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM lessons "
                "WHERE subtopic_id = ? AND deleted_at IS NULL", (subtopic_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO lessons (topic_id, subtopic_id, name, status, "
                "position, created_at, updated_at) "
                "VALUES (?, ?, ?, 'in_progress', ?, ?, ?)",
                (topic_id, subtopic_id, title, position, now, now),
            )
            lesson_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("UPDATE notes SET lesson_id = ?, updated_at = ? WHERE id = ?",
                         (lesson_id, now, note_id))
            adopted += 1
        conn.commit()
    finally:
        conn.close()

    print(f"\nAdopted {adopted} note(s). They now open from the sidebar.")
    print("Restore with: cp '%s' '%s'" % (created.path, db_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
