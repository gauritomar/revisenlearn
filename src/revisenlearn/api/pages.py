"""Pages: every level of the hierarchy, opened the same way.

The user's model, in their words: "a Notion type interface where everything is
a page and pages under pages — when I open a page I should be able to see all
the pages under it too".

So a Subject, a Topic, a Subtopic and a Lesson are all pages. Each one has a
single continuous note (get-or-create, exactly like `/api/notes/ensure`), a
breadcrumb of the pages above it, and a list of the pages inside it. This is
the one endpoint the Roadmap and the note screen both read, so "what is inside
this?" has a single answer rather than one per view.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import Lesson, Note, NoteBlock, Subject, Subtopic, Topic
from .schemas import NoteCreate

router = APIRouter()

KINDS = ("subject", "topic", "subtopic", "lesson")

MODELS = {"subject": Subject, "topic": Topic,
          "subtopic": Subtopic, "lesson": Lesson}


def _row(session: Session, kind: str, page_id: int):
    if kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {KINDS}")
    row = session.get(MODELS[kind], page_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(404, f"{kind.title()} not found")
    return row


def _breadcrumb(session: Session, kind: str, row) -> list[dict]:
    """The pages above this one, outermost first."""
    trail: list[dict] = []

    def push(k: str, r) -> None:
        trail.append({"kind": k, "id": r.id, "name": r.name})

    if kind == "lesson":
        if row.subtopic_id:
            subtopic = session.get(Subtopic, row.subtopic_id)
            topic = session.get(Topic, row.topic_id)
            if topic:
                subject = session.get(Subject, topic.subject_id)
                if subject:
                    push("subject", subject)
                push("topic", topic)
            if subtopic:
                push("subtopic", subtopic)
        else:
            topic = session.get(Topic, row.topic_id)
            if topic:
                subject = session.get(Subject, topic.subject_id)
                if subject:
                    push("subject", subject)
                push("topic", topic)
    elif kind == "subtopic":
        topic = session.get(Topic, row.topic_id)
        if topic:
            subject = session.get(Subject, topic.subject_id)
            if subject:
                push("subject", subject)
            push("topic", topic)
    elif kind == "topic":
        subject = session.get(Subject, row.subject_id)
        if subject:
            push("subject", subject)
    return trail


def _block_count(session: Session, note_id: int | None) -> int:
    if note_id is None:
        return 0
    return len(session.exec(
        select(NoteBlock).where(NoteBlock.note_id == note_id,
                                NoteBlock.deleted_at.is_(None))
    ).all())


def _note_id_for(session: Session, kind: str, page_id: int) -> int | None:
    """The page's note, without creating one — for counting children."""
    stmt = select(Note).where(Note.deleted_at.is_(None),
                              Note.resource_id.is_(None))
    if kind == "lesson":
        stmt = stmt.where(Note.lesson_id == page_id)
    elif kind == "subtopic":
        stmt = stmt.where(Note.subtopic_id == page_id, Note.lesson_id.is_(None))
    elif kind == "topic":
        stmt = stmt.where(Note.topic_id == page_id, Note.subtopic_id.is_(None),
                          Note.lesson_id.is_(None))
    else:
        stmt = stmt.where(Note.subject_id == page_id, Note.topic_id.is_(None),
                          Note.subtopic_id.is_(None), Note.lesson_id.is_(None))
    note = session.exec(stmt.order_by(Note.id)).first()
    return note.id if note else None


def _child(session: Session, kind: str, row, child_count: int) -> dict:
    note_id = _note_id_for(session, kind, row.id)
    return {
        "kind": kind,
        "id": row.id,
        "name": row.name,
        "url": getattr(row, "url", None),
        "note_id": note_id,
        "block_count": _block_count(session, note_id),
        "child_count": child_count,
    }


def children_of(session: Session, kind: str, page_id: int) -> list[dict]:
    """The pages inside this one, in the order the user arranged them."""
    out: list[dict] = []

    if kind == "subject":
        topics = session.exec(
            select(Topic).where(Topic.subject_id == page_id,
                                Topic.deleted_at.is_(None))
            .order_by(Topic.sort_order, Topic.id)
        ).all()
        for topic in topics:
            subs = session.exec(
                select(Subtopic).where(Subtopic.topic_id == topic.id,
                                       Subtopic.deleted_at.is_(None))
            ).all()
            lessons = session.exec(
                select(Lesson).where(Lesson.topic_id == topic.id,
                                     Lesson.subtopic_id.is_(None),
                                     Lesson.deleted_at.is_(None))
            ).all()
            out.append(_child(session, "topic", topic, len(subs) + len(lessons)))

    elif kind == "topic":
        subs = session.exec(
            select(Subtopic).where(Subtopic.topic_id == page_id,
                                   Subtopic.deleted_at.is_(None))
            .order_by(Subtopic.sort_order, Subtopic.id)
        ).all()
        for subtopic in subs:
            lessons = session.exec(
                select(Lesson).where(Lesson.subtopic_id == subtopic.id,
                                     Lesson.deleted_at.is_(None))
            ).all()
            out.append(_child(session, "subtopic", subtopic, len(lessons)))
        # Lessons hanging straight off the topic are peers of its subtopics.
        for lesson in session.exec(
            select(Lesson).where(Lesson.topic_id == page_id,
                                 Lesson.subtopic_id.is_(None),
                                 Lesson.deleted_at.is_(None))
            .order_by(Lesson.position, Lesson.id)
        ).all():
            out.append(_child(session, "lesson", lesson, 0))

    elif kind == "subtopic":
        for lesson in session.exec(
            select(Lesson).where(Lesson.subtopic_id == page_id,
                                 Lesson.deleted_at.is_(None))
            .order_by(Lesson.position, Lesson.id)
        ).all():
            out.append(_child(session, "lesson", lesson, 0))

    # A Lesson is the innermost page: three fixed levels of hierarchy plus
    # lessons, no arbitrary nesting (spec §3 [LOCKED]).
    return out


@router.get("/pages/{kind}/{page_id}")
def get_page(kind: str, page_id: int,
             session: Session = Depends(get_session)) -> dict:
    """Everything the page screen needs: its note, its trail, its contents.

    The note is created on first open, the same get-or-create contract as
    `POST /api/notes/ensure` — opening a page you have never written on should
    put a cursor in front of you, not an empty state with a button.
    """
    from .notes import ensure_note

    row = _row(session, kind, page_id)

    payload = {"subject": NoteCreate(subject_id=page_id),
               "topic": NoteCreate(topic_id=page_id),
               "subtopic": NoteCreate(subtopic_id=page_id),
               "lesson": NoteCreate(lesson_id=page_id)}[kind]
    note = ensure_note(payload, session)

    return {
        "kind": kind,
        "id": row.id,
        "name": row.name,
        "colour": getattr(row, "colour", None),
        "status": getattr(row, "status", None),
        # "I should be able to link certain articles or youtube lectures or
        # leetcode questions … and that link should be displayed when its page
        # is open."
        "url": getattr(row, "url", None),
        "note_id": note.id,
        "breadcrumb": _breadcrumb(session, kind, row),
        "children": children_of(session, kind, page_id),
    }
