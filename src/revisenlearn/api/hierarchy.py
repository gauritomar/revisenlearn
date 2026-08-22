"""Subject / Topic / Subtopic CRUD.

Three fixed levels, no arbitrary nesting (spec §3 **[LOCKED]**). Deletes are
soft (principle §1.7) and cascade *logically* to children so the sidebar tree
hides them, without ever removing a row.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from pydantic import BaseModel, Field as PydanticField

from ..db import get_session
from ..models import ChecklistItem, Lesson, Subject, Subtopic, Topic
from .schemas import (
    LessonBrief,
    SubjectCreate,
    SubjectOut,
    SubjectUpdate,
    SubtopicCreate,
    SubtopicOut,
    SubtopicUpdate,
    TopicCreate,
    TopicOut,
    TopicUpdate,
)

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Subjects --------------------------------------------------------------

@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(session: Session = Depends(get_session)) -> list[SubjectOut]:
    """The full tree for the left sidebar, in one round trip."""
    subjects = session.exec(
        select(Subject).where(Subject.deleted_at.is_(None)).order_by(
            Subject.sort_order, Subject.id
        )
    ).all()
    topics = session.exec(
        select(Topic).where(Topic.deleted_at.is_(None)).order_by(
            Topic.sort_order, Topic.id
        )
    ).all()
    subtopics = session.exec(
        select(Subtopic).where(Subtopic.deleted_at.is_(None)).order_by(
            Subtopic.sort_order, Subtopic.id
        )
    ).all()

    # Consolidated addendum §5 — the sidebar is lesson-centric now, so the
    # tree carries lessons and their checklist counts too. One extra pair of
    # queries, still one round trip.
    lessons = session.exec(
        select(Lesson).where(Lesson.deleted_at.is_(None)).order_by(
            Lesson.position, Lesson.id
        )
    ).all()
    counts: dict[int, list[int]] = {}
    for item in session.exec(
        select(ChecklistItem).where(ChecklistItem.lesson_id.is_not(None))
    ).all():
        tally = counts.setdefault(item.lesson_id, [0, 0])
        tally[0] += 1
        tally[1] += 1 if item.checked else 0

    lessons_by_subtopic: dict[int, list[LessonBrief]] = {}
    lessons_by_topic: dict[int, list[LessonBrief]] = {}
    for lesson in lessons:
        total, done = counts.get(lesson.id, (0, 0))
        brief = LessonBrief(
            id=lesson.id, topic_id=lesson.topic_id,
            subtopic_id=lesson.subtopic_id, name=lesson.name,
            status=lesson.status, position=lesson.position, url=lesson.url,
            checklist_total=total, checklist_done=done,
        )
        if lesson.subtopic_id is not None:
            lessons_by_subtopic.setdefault(lesson.subtopic_id, []).append(brief)
        else:
            lessons_by_topic.setdefault(lesson.topic_id, []).append(brief)

    subs_by_topic: dict[int, list[SubtopicOut]] = {}
    for st in subtopics:
        subs_by_topic.setdefault(st.topic_id, []).append(
            SubtopicOut(id=st.id, topic_id=st.topic_id, name=st.name,
                        sort_order=st.sort_order, url=st.url,
                        lessons=lessons_by_subtopic.get(st.id, []))
        )

    topics_by_subject: dict[int, list[TopicOut]] = {}
    for t in topics:
        topics_by_subject.setdefault(t.subject_id, []).append(
            TopicOut(id=t.id, subject_id=t.subject_id, name=t.name,
                     sort_order=t.sort_order, url=t.url,
                     subtopics=subs_by_topic.get(t.id, []),
                     lessons=lessons_by_topic.get(t.id, []))
        )

    return [
        SubjectOut(id=s.id, name=s.name, colour=s.colour,
                   sort_order=s.sort_order, url=s.url,
                   topics=topics_by_subject.get(s.id, []))
        for s in subjects
    ]


@router.post("/subjects", response_model=SubjectOut, status_code=201)
def create_subject(payload: SubjectCreate,
                   session: Session = Depends(get_session)) -> SubjectOut:
    subject = Subject(**payload.model_dump())
    session.add(subject)
    session.flush()
    return SubjectOut(id=subject.id, name=subject.name, colour=subject.colour,
                      sort_order=subject.sort_order, topics=[])


@router.patch("/subjects/{subject_id}", response_model=SubjectOut)
def update_subject(subject_id: int, payload: SubjectUpdate,
                   session: Session = Depends(get_session)) -> SubjectOut:
    subject = session.get(Subject, subject_id)
    if subject is None or subject.deleted_at is not None:
        raise HTTPException(404, "Subject not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(subject, field, value)
    session.add(subject)
    session.flush()
    return SubjectOut(id=subject.id, name=subject.name, colour=subject.colour,
                      sort_order=subject.sort_order, topics=[])


@router.delete("/subjects/{subject_id}", status_code=204)
def delete_subject(subject_id: int, session: Session = Depends(get_session)) -> None:
    subject = session.get(Subject, subject_id)
    if subject is None or subject.deleted_at is not None:
        raise HTTPException(404, "Subject not found")
    now = _now()
    subject.deleted_at = now
    topics = session.exec(
        select(Topic).where(Topic.subject_id == subject_id,
                            Topic.deleted_at.is_(None))
    ).all()
    for topic in topics:
        topic.deleted_at = now
        for st in session.exec(
            select(Subtopic).where(Subtopic.topic_id == topic.id,
                                   Subtopic.deleted_at.is_(None))
        ).all():
            st.deleted_at = now


# --- Topics ----------------------------------------------------------------

@router.post("/topics", response_model=TopicOut, status_code=201)
def create_topic(payload: TopicCreate,
                 session: Session = Depends(get_session)) -> TopicOut:
    subject = session.get(Subject, payload.subject_id)
    if subject is None or subject.deleted_at is not None:
        raise HTTPException(404, "Subject not found")
    topic = Topic(**payload.model_dump())
    session.add(topic)
    session.flush()
    return TopicOut(id=topic.id, subject_id=topic.subject_id, name=topic.name,
                    sort_order=topic.sort_order, subtopics=[])


@router.patch("/topics/{topic_id}", response_model=TopicOut)
def update_topic(topic_id: int, payload: TopicUpdate,
                 session: Session = Depends(get_session)) -> TopicOut:
    topic = session.get(Topic, topic_id)
    if topic is None or topic.deleted_at is not None:
        raise HTTPException(404, "Topic not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(topic, field, value)
    session.add(topic)
    session.flush()
    return TopicOut(id=topic.id, subject_id=topic.subject_id, name=topic.name,
                    sort_order=topic.sort_order, subtopics=[])


@router.delete("/topics/{topic_id}", status_code=204)
def delete_topic(topic_id: int, session: Session = Depends(get_session)) -> None:
    topic = session.get(Topic, topic_id)
    if topic is None or topic.deleted_at is not None:
        raise HTTPException(404, "Topic not found")
    now = _now()
    topic.deleted_at = now
    for st in session.exec(
        select(Subtopic).where(Subtopic.topic_id == topic_id,
                               Subtopic.deleted_at.is_(None))
    ).all():
        st.deleted_at = now


# --- Subtopics -------------------------------------------------------------

@router.post("/subtopics", response_model=SubtopicOut, status_code=201)
def create_subtopic(payload: SubtopicCreate,
                    session: Session = Depends(get_session)) -> SubtopicOut:
    topic = session.get(Topic, payload.topic_id)
    if topic is None or topic.deleted_at is not None:
        raise HTTPException(404, "Topic not found")
    subtopic = Subtopic(**payload.model_dump())
    session.add(subtopic)
    session.flush()
    return SubtopicOut(id=subtopic.id, topic_id=subtopic.topic_id,
                       name=subtopic.name, sort_order=subtopic.sort_order)


@router.patch("/subtopics/{subtopic_id}", response_model=SubtopicOut)
def update_subtopic(subtopic_id: int, payload: SubtopicUpdate,
                    session: Session = Depends(get_session)) -> SubtopicOut:
    subtopic = session.get(Subtopic, subtopic_id)
    if subtopic is None or subtopic.deleted_at is not None:
        raise HTTPException(404, "Subtopic not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(subtopic, field, value)
    session.add(subtopic)
    session.flush()
    return SubtopicOut(id=subtopic.id, topic_id=subtopic.topic_id,
                       name=subtopic.name, sort_order=subtopic.sort_order)


@router.delete("/subtopics/{subtopic_id}", status_code=204)
def delete_subtopic(subtopic_id: int, session: Session = Depends(get_session)) -> None:
    subtopic = session.get(Subtopic, subtopic_id)
    if subtopic is None or subtopic.deleted_at is not None:
        raise HTTPException(404, "Subtopic not found")
    subtopic.deleted_at = _now()


# --------------------------------------------------------------------------
# Moving and reordering (consolidated addendum §5)
#
# "**Drag-and-drop reordering** within the sidebar tree, updating each item's
# `position` column. Also add a **"Move to..." action** … that reparents it to
# a different Subject/Topic/Subtopic via a picker."
#
# Both are the same operation — a new parent (possibly the current one) and a
# new index among its children — so they share one endpoint. Positions are
# renumbered densely on every move, which keeps the ordering stable no matter
# what the rows looked like before.
# --------------------------------------------------------------------------

KINDS = ("subject", "topic", "subtopic", "lesson")


class MoveIn(BaseModel):
    kind: str
    id: int
    #: The new parent's id: subject for a topic, topic for a subtopic, topic
    #: **or** subtopic for a lesson. Ignored for a subject, which has none.
    parent_id: int | None = None
    #: For a lesson only: move it under a subtopic, or None for straight onto
    #: the topic. Absent means "keep where it is".
    subtopic_id: int | None = None
    position: int = PydanticField(default=0, ge=0)


def _order_field(kind: str) -> str:
    return "position" if kind == "lesson" else "sort_order"


def _siblings(session: Session, kind: str, parent_id: int | None,
              subtopic_id: int | None) -> list:
    if kind == "subject":
        stmt = select(Subject).where(Subject.deleted_at.is_(None))
    elif kind == "topic":
        stmt = select(Topic).where(Topic.deleted_at.is_(None),
                                   Topic.subject_id == parent_id)
    elif kind == "subtopic":
        stmt = select(Subtopic).where(Subtopic.deleted_at.is_(None),
                                      Subtopic.topic_id == parent_id)
    else:
        stmt = select(Lesson).where(Lesson.deleted_at.is_(None),
                                    Lesson.topic_id == parent_id)
        stmt = (stmt.where(Lesson.subtopic_id == subtopic_id)
                if subtopic_id is not None
                else stmt.where(Lesson.subtopic_id.is_(None)))
    field = _order_field(kind)
    rows = list(session.exec(stmt).all())
    rows.sort(key=lambda r: (getattr(r, field), r.id))
    return rows


@router.post("/tree/move")
def move(payload: MoveIn, session: Session = Depends(get_session)) -> dict:
    """Reorder within a parent, or reparent, in one call."""
    if payload.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {KINDS}")

    model = {"subject": Subject, "topic": Topic,
             "subtopic": Subtopic, "lesson": Lesson}[payload.kind]
    row = session.get(model, payload.id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(404, f"{payload.kind.title()} not found")

    # Work out where it is going, validating the new parent as we do.
    parent_id, subtopic_id = payload.parent_id, payload.subtopic_id
    if payload.kind == "subject":
        parent_id = subtopic_id = None
    elif payload.kind == "topic":
        parent_id = parent_id if parent_id is not None else row.subject_id
        if session.get(Subject, parent_id) is None:
            raise HTTPException(404, "Subject not found")
        row.subject_id = parent_id
    elif payload.kind == "subtopic":
        parent_id = parent_id if parent_id is not None else row.topic_id
        if session.get(Topic, parent_id) is None:
            raise HTTPException(404, "Topic not found")
        row.topic_id = parent_id
    else:
        parent_id = parent_id if parent_id is not None else row.topic_id
        topic = session.get(Topic, parent_id)
        if topic is None or topic.deleted_at is not None:
            raise HTTPException(404, "Topic not found")
        if subtopic_id is not None:
            subtopic = session.get(Subtopic, subtopic_id)
            if subtopic is None or subtopic.deleted_at is not None:
                raise HTTPException(404, "Subtopic not found")
            # A lesson may not straddle the tree: its subtopic decides its
            # topic, so a mismatched pair is a bad request, not a silent fix.
            if subtopic.topic_id != parent_id:
                raise HTTPException(400, "Subtopic does not belong to that topic")
        row.topic_id = parent_id
        row.subtopic_id = subtopic_id

    field = _order_field(payload.kind)
    ordered = [r for r in _siblings(session, payload.kind, parent_id, subtopic_id)
               if r.id != row.id]
    index = min(payload.position, len(ordered))
    ordered.insert(index, row)
    for i, sibling in enumerate(ordered):
        if getattr(sibling, field) != i:
            setattr(sibling, field, i)
            session.add(sibling)
    # Only Lesson carries `updated_at`; the three hierarchy levels do not,
    # and assigning one would silently create an attribute that never lands.
    if hasattr(type(row), "updated_at"):
        row.updated_at = _now()
    session.add(row)
    session.flush()

    return {"kind": payload.kind, "id": row.id, "position": index,
            "siblings": [r.id for r in ordered]}
