"""Lessons, Items, Todos and the progress rollup (addendum §1–§4).

Addendum §0.1 **[structural]**: "Practice tracking and concept learning are
different activities and should not be forced through the same pipeline …
checking a box should never create a concept or touch FSRS."

Nothing in this module writes a concept, a review item or a review log. That
separation is the point of the layer.

Addendum §5 **[LOCKED — important]**: this progress layer and FSRS mastery
"must not share a visual language". A green 100% here means "I checked every
box"; a green Mastered badge means "I can recall and explain this reliably,
recently". The API therefore returns a bare percentage with no badge, no state
and no colour — there is deliberately nothing here for a UI to traffic-light.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlmodel import Session, select

from .models import (
    ChecklistItem,
    Lesson,
    Subject,
    Subtopic,
    Todo,
    Topic,
)

log = logging.getLogger(__name__)

#: Only used when a lesson has no checklist to measure. `revisit` sits at 50:
#: the work was done once, and is being redone.
LESSON_STATUS_PCT = {"not_started": 0.0, "in_progress": 50.0, "done": 100.0,
                     "revisit": 50.0}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mean(values: list[float]) -> float | None:
    """`None`, not 0, when there is nothing underneath.

    Addendum §4: "Percentages with no data underneath render as an empty/grey
    state, not 0% — an empty subject shouldn't look '0% learned'."
    """
    return sum(values) / len(values) if values else None


# --------------------------------------------------------------------------
# §4 Progress rollup **[LOCKED]**
# --------------------------------------------------------------------------

def live_items(session: Session, lesson_id: int) -> list[ChecklistItem]:
    """A lesson's checklist, derived from its note's blocks.

    Consolidated addendum §2 replaced the hand-authored `lesson_items` table
    with this projection, so progress now follows what the user actually wrote
    rather than a separately maintained list.
    """
    return list(session.exec(
        select(ChecklistItem)
        .where(ChecklistItem.lesson_id == lesson_id)
        .order_by(ChecklistItem.position, ChecklistItem.id)
    ).all())


def lesson_pct(session: Session, lesson: Lesson) -> float:
    items = live_items(session, lesson.id)
    if items:
        return 100.0 * sum(1 for i in items if i.checked) / len(items)
    return LESSON_STATUS_PCT.get(lesson.status, 0.0)


def _lessons_of_subtopic(session: Session, subtopic_id: int) -> list[Lesson]:
    return list(session.exec(
        select(Lesson)
        .where(Lesson.subtopic_id == subtopic_id, Lesson.deleted_at.is_(None))
        .order_by(Lesson.position, Lesson.id)
    ).all())


def _lessons_direct_on_topic(session: Session, topic_id: int) -> list[Lesson]:
    return list(session.exec(
        select(Lesson)
        .where(Lesson.topic_id == topic_id,
               Lesson.subtopic_id.is_(None),
               Lesson.deleted_at.is_(None))
        .order_by(Lesson.position, Lesson.id)
    ).all())


def subtopic_pct(session: Session, subtopic_id: int) -> float | None:
    lessons = _lessons_of_subtopic(session, subtopic_id)
    return _mean([lesson_pct(session, l) for l in lessons])


def topic_pct(session: Session, topic_id: int) -> float | None:
    """Subtopic rollups and lessons hanging directly off the topic are peers in
    the same average (addendum §4)."""
    subtopics = session.exec(
        select(Subtopic).where(Subtopic.topic_id == topic_id,
                               Subtopic.deleted_at.is_(None))
    ).all()

    values: list[float] = []
    for subtopic in subtopics:
        value = subtopic_pct(session, subtopic.id)
        if value is not None:          # only subtopics that have lessons
            values.append(value)
    values.extend(
        lesson_pct(session, l) for l in _lessons_direct_on_topic(session, topic_id)
    )
    return _mean(values)


def subject_pct(session: Session, subject_id: int) -> float | None:
    topics = session.exec(
        select(Topic).where(Topic.subject_id == subject_id,
                            Topic.deleted_at.is_(None))
    ).all()
    values = [v for v in (topic_pct(session, t.id) for t in topics)
              if v is not None]
    return _mean(values)


# --------------------------------------------------------------------------
# Status coupling (addendum §4)
# --------------------------------------------------------------------------

def sync_lesson_status(session: Session, lesson: Lesson) -> bool:
    """"Marking every Item under a Lesson done auto-flips the Lesson's status
    to `done`."

    Only that direction is automatic. The status stays "directly clickable and
    overridable at any time", so unticking an item does not drag a lesson the
    user deliberately marked done back out of it.
    """
    items = live_items(session, lesson.id)
    if not items:
        return False
    if all(i.checked for i in items) and lesson.status != "done":
        lesson.status = "done"
        lesson.updated_at = _now()
        session.add(lesson)
        session.flush()
        return True
    return False


def set_item_done(session: Session, item: ChecklistItem, done: bool) -> None:
    """Toggle a checklist item from outside the note editor.

    The write goes through `checklist.set_checked`, which updates the *note
    block* and re-derives this row — addendum §2 forbids a second, divergent
    copy of the state.
    """
    from .checklist import set_checked

    set_checked(session, item.id, done)

    lesson = session.get(Lesson, item.lesson_id) if item.lesson_id else None
    if lesson is not None and done:
        sync_lesson_status(session, lesson)


# --------------------------------------------------------------------------
# §6 Roadmap view — the full tree with rollups
# --------------------------------------------------------------------------

def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def build_roadmap(session: Session) -> dict:
    """"Always shows everything, completed included — no hide-completed toggle
    here; seeing the whole shape of a curriculum, finished parts included, is
    the point of this view." (addendum §6)"""
    subjects = session.exec(
        select(Subject).where(Subject.deleted_at.is_(None))
        .order_by(Subject.sort_order, Subject.id)
    ).all()

    out = []
    for subject in subjects:
        topics = session.exec(
            select(Topic).where(Topic.subject_id == subject.id,
                                Topic.deleted_at.is_(None))
            .order_by(Topic.sort_order, Topic.id)
        ).all()

        topic_nodes = []
        for topic in topics:
            subtopics = session.exec(
                select(Subtopic).where(Subtopic.topic_id == topic.id,
                                       Subtopic.deleted_at.is_(None))
                .order_by(Subtopic.sort_order, Subtopic.id)
            ).all()

            subtopic_nodes = [
                {
                    "id": subtopic.id,
                    "name": subtopic.name,
                    "pct": _round(subtopic_pct(session, subtopic.id)),
                    "lessons": [
                        _lesson_node(session, l)
                        for l in _lessons_of_subtopic(session, subtopic.id)
                    ],
                }
                for subtopic in subtopics
            ]

            topic_nodes.append({
                "id": topic.id,
                "name": topic.name,
                "pct": _round(topic_pct(session, topic.id)),
                "subtopics": subtopic_nodes,
                # Lessons attached straight to the topic, with no subtopic.
                "lessons": [
                    _lesson_node(session, l)
                    for l in _lessons_direct_on_topic(session, topic.id)
                ],
            })

        out.append({
            "id": subject.id,
            "name": subject.name,
            "colour": subject.colour,
            "pct": _round(subject_pct(session, subject.id)),
            "topics": topic_nodes,
        })
    return {"subjects": out}


def _lesson_node(session: Session, lesson: Lesson) -> dict:
    items = live_items(session, lesson.id)
    return {
        "id": lesson.id,
        "name": lesson.name,
        "status": lesson.status,
        "position": lesson.position,
        "topic_id": lesson.topic_id,
        "subtopic_id": lesson.subtopic_id,
        "pct": _round(lesson_pct(session, lesson)),
        "items": [
            {"id": i.id, "title": i.text, "done": i.checked,
             "url": i.url, "note_block_id": i.note_block_id,
             "position": i.position}
            for i in items
        ],
    }


# --------------------------------------------------------------------------
# §6 Todos view — flat, filterable, cross-cutting
# --------------------------------------------------------------------------

def todo_board(session: Session, *, subject_id: int | None = None,
               topic_id: int | None = None, has_due_date: bool | None = None,
               hide_completed: bool = True) -> dict:
    """"A flat, filterable, cross-cutting list combining standalone Todos and
    any open Lesson/Item across every subject." (addendum §6)

    This is the view with the hide-completed toggle, default on — its job is
    "what's left", unlike Roadmap.
    """
    entries: list[dict] = []

    todos = session.exec(
        select(Todo).where(Todo.deleted_at.is_(None))
        .order_by(Todo.position, Todo.id)
    ).all()
    for todo in todos:
        entries.append({
            "kind": "todo",
            "id": todo.id,
            "title": todo.title,
            "done": todo.done,
            "due_date": todo.due_date.isoformat() if todo.due_date else None,
            "subject_id": todo.subject_id,
            "topic_id": todo.topic_id,
            "lesson_id": None,
            "context": None,
        })

    lessons = session.exec(
        select(Lesson).where(Lesson.deleted_at.is_(None))
        .order_by(Lesson.position, Lesson.id)
    ).all()
    topics = {t.id: t for t in session.exec(select(Topic)).all()}
    subtopics = {s.id: s for s in session.exec(select(Subtopic)).all()}

    for lesson in lessons:
        topic = topics.get(lesson.topic_id)
        subtopic = subtopics.get(lesson.subtopic_id) if lesson.subtopic_id else None
        context = " > ".join(
            part for part in [topic.name if topic else None,
                              subtopic.name if subtopic else None] if part
        )
        entries.append({
            "kind": "lesson",
            "id": lesson.id,
            "title": lesson.name,
            "done": lesson.status == "done",
            "due_date": None,
            "subject_id": topic.subject_id if topic else None,
            "topic_id": lesson.topic_id,
            "lesson_id": lesson.id,
            "context": context or None,
        })
        for item in live_items(session, lesson.id):
            entries.append({
                "kind": "lesson_item",
                "id": item.id,
                "title": item.text,
                "done": item.checked,
                "due_date": None,
                "subject_id": topic.subject_id if topic else None,
                "topic_id": lesson.topic_id,
                "lesson_id": lesson.id,
                "context": lesson.name,
            })

    if subject_id is not None:
        entries = [e for e in entries if e["subject_id"] == subject_id]
    if topic_id is not None:
        entries = [e for e in entries if e["topic_id"] == topic_id]
    if has_due_date is True:
        entries = [e for e in entries if e["due_date"]]
    elif has_due_date is False:
        entries = [e for e in entries if not e["due_date"]]
    if hide_completed:
        entries = [e for e in entries if not e["done"]]

    # Nearest due date first, then undated.
    entries.sort(key=lambda e: (e["due_date"] is None, e["due_date"] or "",
                                e["kind"], e["title"]))
    return {"entries": entries, "hide_completed": hide_completed}


def dashboard_todos(session: Session, limit: int = 7) -> list[dict]:
    """Addendum §6 — "a short Todos panel (5–7 items, standalone todos plus any
    due-dated items, nearest due date first)"."""
    board = todo_board(session, hide_completed=True)
    return board["entries"][:limit]
