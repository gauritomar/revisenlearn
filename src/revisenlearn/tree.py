"""Is this note still somewhere the user can see it?

Nothing is ever hard-deleted (principle §1.7), so deleting a subtopic leaves
its notes and blocks exactly where they were. From the user's point of view
that writing is gone: it is not in the tree, not on a page, not reachable. Two
places must agree about that —

  * the pipeline, which must not charge for sending writing the user threw
    away ("deleted notes etc should not appear in my send to gemini");
  * the calendar, which must not light up a day for a page that no longer
    exists.

So the rule lives here rather than being written twice.
"""

from __future__ import annotations

from sqlmodel import Session

from .models import Lesson, Note, NoteBlock, Subject, Subtopic, Topic

#: Block types that are furniture rather than writing. A date divider is
#: written by the app itself; a divider has no text at all.
FURNITURE = {"date_divider", "divider"}


def on_a_live_page(session: Session, note: Note) -> bool:
    """False when a note is not somewhere the user studies.

    That covers two cases: a note whose subject, topic, subtopic or lesson has
    been deleted, and a scratch page — the Resources page is a place to keep
    links, not material to be examined on, so it is never sent to the model
    and never counted as a day's work.
    """
    if note.scratch_key is not None:
        return False

    for row_id, model in ((note.lesson_id, Lesson),
                          (note.subtopic_id, Subtopic),
                          (note.topic_id, Topic),
                          (note.subject_id, Subject)):
        if row_id is None:
            continue
        row = session.get(model, row_id)
        if row is None or row.deleted_at is not None:
            return False
    return True


def has_real_content(block: NoteBlock) -> bool:
    """Something the user actually wrote.

    Opening a page creates its note, so "a note exists" no longer means "there
    is writing here" — an empty page note must not show up as a day's work or
    as something to process.
    """
    if block.block_type in FURNITURE:
        return False
    text = (block.text or "").strip()
    if block.block_type == "checklist_item":
        from .checklist import parse_checkbox

        parsed = parse_checkbox(text)
        text = (parsed[1] if parsed else text).strip()
    return bool(text)
