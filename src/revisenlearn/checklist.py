"""Checklist items, derived from note blocks (consolidated addendum §2).

"`checklist_items` rows are created/updated/deleted automatically whenever a
`checklist_item` block is saved … **This table has no dedicated CRUD UI.** The
only way to create or edit a checklist item is by typing or checking a box
inside the note editor. The Roadmap/Todos views may toggle `checked` from
outside the note, but that write goes through to the underlying `note_blocks`
row — never a separate, divergent copy of the state."

So this module is a projection, in one direction only:

    note_blocks (source of truth)  ──reconcile──▶  checklist_items (derived)

Every write path — typing in the editor, ticking a box in the right panel,
ticking one in Roadmap — lands on the block first and then calls
`reconcile_note`. There is deliberately no way to write a `checklist_items` row
directly.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlmodel import Session, select

from .models import ChecklistItem, Note, NoteBlock

log = logging.getLogger(__name__)

#: Addendum §2 — "Typing `- [ ] text` creates one; `- [x] text` creates it
#: pre-checked." Matched on save so the syntax works however the text arrived,
#: including a paste.
CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[(?P<mark>[ xX])\]\s*(?P<text>.*)$")

#: A bare URL anywhere in the line. §4 turns this into a Resource.
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_checkbox(text: str) -> tuple[bool, str] | None:
    """`"- [x] Read the paper"` → `(True, "Read the paper")`, else None."""
    match = CHECKBOX_RE.match(text or "")
    if match is None:
        return None
    return match.group("mark").lower() == "x", match.group("text").strip()


def first_url(text: str) -> str | None:
    match = URL_RE.search(text or "")
    return match.group(0).rstrip(".,;:") if match else None


def normalise_url(url: str) -> str:
    """Enough normalisation to stop the same link becoming two Resources.

    Deliberately conservative: lowercasing the host and dropping a trailing
    slash and fragment is safe, but query strings are load-bearing on the sites
    this app is aimed at (`?v=` on YouTube, `?key=` elsewhere), so they stay.
    """
    from urllib.parse import urlsplit, urlunsplit

    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    if not parts.scheme or not parts.netloc:
        return url.strip()

    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


# --------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------

def reconcile_note(session: Session, note_id: int) -> dict:
    """Rebuild this note's `checklist_items` from its blocks.

    Called after every block save. Returns counts so callers can log what
    changed without re-querying.
    """
    note = session.get(Note, note_id)
    if note is None:
        return {"created": 0, "updated": 0, "removed": 0}

    blocks = list(session.exec(
        select(NoteBlock)
        .where(NoteBlock.note_id == note_id, NoteBlock.deleted_at.is_(None))
        .order_by(NoteBlock.position, NoteBlock.id)
    ).all())

    existing = {
        row.note_block_id: row for row in session.exec(
            select(ChecklistItem).where(ChecklistItem.note_id == note_id)
        ).all()
    }

    # First pass: the rows themselves, keyed by block.
    by_block: dict[int, ChecklistItem] = {}
    created = updated = 0

    for position, block in enumerate(blocks):
        if block.block_type != "checklist_item":
            continue

        # Store the content, not the syntax: "- [x] Read the paper" projects
        # as "Read the paper". The marker belongs to the editor, and leaking
        # it here would put raw markdown in the Todos board and right panel.
        parsed = parse_checkbox(block.text or "")
        text = parsed[1] if parsed else (block.text or "").strip()
        url = block.url or first_url(block.text or "")
        row = existing.get(block.id)

        if row is None:
            row = ChecklistItem(
                note_block_id=block.id,
                note_id=note_id,
                lesson_id=note.lesson_id,
                text=text,
                url=url,
                checked=block.checked,
                completed_at=_now() if block.checked else None,
                position=position,
            )
            session.add(row)
            created += 1
        else:
            changed = (
                row.text != text
                or row.url != url
                or row.checked != block.checked
                or row.position != position
                or row.lesson_id != note.lesson_id
            )
            if changed:
                # completed_at only moves on an actual transition, so an edit
                # to the text does not restamp when it was finished.
                if block.checked and not row.checked:
                    row.completed_at = _now()
                elif not block.checked:
                    row.completed_at = None
                row.text = text
                row.url = url
                row.checked = block.checked
                row.position = position
                row.lesson_id = note.lesson_id
                row.updated_at = _now()
                session.add(row)
                updated += 1
        by_block[block.id] = row

    session.flush()

    # Second pass: nesting, once every row has an id.
    for block in blocks:
        row = by_block.get(block.id)
        if row is None:
            continue
        parent = by_block.get(block.parent_block_id) if block.parent_block_id else None
        parent_id = parent.id if parent else None
        if row.parent_checklist_item_id != parent_id:
            row.parent_checklist_item_id = parent_id
            session.add(row)

    # A block that stopped being a checklist item, or was deleted, loses its
    # row. This is a projection: there is nothing here worth keeping on its own.
    removed = 0
    for block_id, row in existing.items():
        if block_id not in by_block:
            session.delete(row)
            removed += 1

    session.flush()
    return {"created": created, "updated": updated, "removed": removed}


def set_checked(session: Session, checklist_item_id: int,
                checked: bool) -> ChecklistItem:
    """Toggle from outside the note editor (Roadmap, right panel).

    Addendum §2: "that write goes through to the underlying `note_blocks` row —
    never a separate, divergent copy of the state." So this writes the block,
    then re-derives.
    """
    row = session.get(ChecklistItem, checklist_item_id)
    if row is None:
        raise LookupError("Checklist item not found")

    block = session.get(NoteBlock, row.note_block_id)
    if block is None or block.deleted_at is not None:
        raise LookupError("The note block behind that item is gone")

    block.checked = checked
    # Keep the written text in step, so reopening the note shows the tick.
    parsed = parse_checkbox(block.text or "")
    body = parsed[1] if parsed else (block.text or "").strip()
    block.text = f"- [{'x' if checked else ' '}] {body}"
    block.updated_at = _now()
    session.add(block)
    session.flush()

    reconcile_note(session, row.note_id)
    session.flush()
    refreshed = session.get(ChecklistItem, checklist_item_id)
    return refreshed or row


def for_lesson(session: Session, lesson_id: int) -> list[ChecklistItem]:
    return list(session.exec(
        select(ChecklistItem)
        .where(ChecklistItem.lesson_id == lesson_id)
        .order_by(ChecklistItem.position, ChecklistItem.id)
    ).all())


def for_note(session: Session, note_id: int) -> list[ChecklistItem]:
    return list(session.exec(
        select(ChecklistItem)
        .where(ChecklistItem.note_id == note_id)
        .order_by(ChecklistItem.position, ChecklistItem.id)
    ).all())
