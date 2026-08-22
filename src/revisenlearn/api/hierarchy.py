"""Subject / Topic / Subtopic CRUD.

Three fixed levels, no arbitrary nesting (spec §3 **[LOCKED]**). Deletes are
soft (principle §1.7) and cascade *logically* to children so the sidebar tree
hides them, without ever removing a row.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import Subject, Subtopic, Topic
from .schemas import (
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

    subs_by_topic: dict[int, list[SubtopicOut]] = {}
    for st in subtopics:
        subs_by_topic.setdefault(st.topic_id, []).append(
            SubtopicOut(id=st.id, topic_id=st.topic_id, name=st.name,
                        sort_order=st.sort_order)
        )

    topics_by_subject: dict[int, list[TopicOut]] = {}
    for t in topics:
        topics_by_subject.setdefault(t.subject_id, []).append(
            TopicOut(id=t.id, subject_id=t.subject_id, name=t.name,
                     sort_order=t.sort_order, subtopics=subs_by_topic.get(t.id, []))
        )

    return [
        SubjectOut(id=s.id, name=s.name, colour=s.colour, sort_order=s.sort_order,
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
