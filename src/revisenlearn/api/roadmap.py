"""Lessons, Items, Todos, links, Roadmap and the Todos board (addendum §10)."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .. import roadmap as service
from ..db import get_session
from ..models import (
    LESSON_STATUSES,
    ChecklistItem,
    Lesson,
    LessonResourceLink,
    Note,
    NoteLessonLink,
    NoteResourceLink,
    Resource,
    Subtopic,
    Todo,
    Topic,
)

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

class LessonCreate(BaseModel):
    topic_id: int
    subtopic_id: int | None = None
    name: str = Field(min_length=1, max_length=300)
    position: int | None = None
    status: str = "not_started"


class LessonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    status: str | None = None
    position: int | None = None
    subtopic_id: int | None = None


class ItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    position: int | None = None


class ItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    done: bool | None = None
    position: int | None = None


class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    subject_id: int | None = None
    topic_id: int | None = None
    due_date: date | None = None


class TodoUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    subject_id: int | None = None
    topic_id: int | None = None
    due_date: date | None = None
    done: bool | None = None
    position: int | None = None


def _lesson_out(session: Session, lesson: Lesson) -> dict:
    return service._lesson_node(session, lesson)


def _todo_out(todo: Todo) -> dict:
    return {
        "id": todo.id, "title": todo.title, "done": todo.done,
        "due_date": todo.due_date.isoformat() if todo.due_date else None,
        "subject_id": todo.subject_id, "topic_id": todo.topic_id,
        "position": todo.position,
    }


def _next_position(session: Session, model, **filters) -> int:
    stmt = select(model).where(model.deleted_at.is_(None))
    for field, value in filters.items():
        column = getattr(model, field)
        stmt = stmt.where(column.is_(None) if value is None else column == value)
    rows = session.exec(stmt).all()
    return max((r.position for r in rows), default=-1) + 1


# --------------------------------------------------------------------------
# Lessons
# --------------------------------------------------------------------------

@router.get("/lessons")
def list_lessons(topic_id: int | None = Query(default=None),
                 subtopic_id: int | None = Query(default=None),
                 session: Session = Depends(get_session)) -> list[dict]:
    stmt = select(Lesson).where(Lesson.deleted_at.is_(None))
    if topic_id is not None:
        stmt = stmt.where(Lesson.topic_id == topic_id)
    if subtopic_id is not None:
        stmt = stmt.where(Lesson.subtopic_id == subtopic_id)
    rows = session.exec(stmt.order_by(Lesson.position, Lesson.id)).all()
    return [_lesson_out(session, l) for l in rows]


@router.post("/lessons", status_code=201)
def create_lesson(payload: LessonCreate,
                  session: Session = Depends(get_session)) -> dict:
    if payload.status not in LESSON_STATUSES:
        raise HTTPException(400, f"status must be one of {LESSON_STATUSES}")
    topic = session.get(Topic, payload.topic_id)
    if topic is None or topic.deleted_at is not None:
        raise HTTPException(404, "Topic not found")
    if payload.subtopic_id is not None:
        subtopic = session.get(Subtopic, payload.subtopic_id)
        if subtopic is None or subtopic.topic_id != payload.topic_id:
            raise HTTPException(400, "Subtopic does not belong to that topic")

    lesson = Lesson(
        topic_id=payload.topic_id,
        subtopic_id=payload.subtopic_id,
        name=payload.name.strip(),
        status=payload.status,
        position=(payload.position if payload.position is not None
                  else _next_position(session, Lesson,
                                      topic_id=payload.topic_id,
                                      subtopic_id=payload.subtopic_id)),
    )
    session.add(lesson)
    session.flush()
    return _lesson_out(session, lesson)


@router.patch("/lessons/{lesson_id}")
def update_lesson(lesson_id: int, payload: LessonUpdate,
                  session: Session = Depends(get_session)) -> dict:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.deleted_at is not None:
        raise HTTPException(404, "Lesson not found")
    fields = payload.model_dump(exclude_unset=True)
    if "status" in fields and fields["status"] not in LESSON_STATUSES:
        raise HTTPException(400, f"status must be one of {LESSON_STATUSES}")
    for field, value in fields.items():
        setattr(lesson, field, value)
    lesson.updated_at = _now()
    session.add(lesson)
    session.flush()
    return _lesson_out(session, lesson)


@router.delete("/lessons/{lesson_id}", status_code=204)
def delete_lesson(lesson_id: int, session: Session = Depends(get_session)) -> None:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.deleted_at is not None:
        raise HTTPException(404, "Lesson not found")
    now = _now()
    lesson.deleted_at = now
    for item in service.live_items(session, lesson_id):
        item.deleted_at = now
        session.add(item)


# --------------------------------------------------------------------------
# Lesson checklist (consolidated addendum §2)
#
# Read-only plus a toggle. "This table has no dedicated CRUD UI. The only way
# to create or edit a checklist item is by typing or checking a box inside the
# note editor." Creating and editing therefore happen through
# PUT /api/notes/{id}/blocks like any other block; there is deliberately no
# POST or PATCH for text here.
# --------------------------------------------------------------------------

class ChecklistToggle(BaseModel):
    checked: bool


def _checklist_out(item: ChecklistItem) -> dict:
    return {
        "id": item.id,
        "note_block_id": item.note_block_id,
        "note_id": item.note_id,
        "lesson_id": item.lesson_id,
        "parent_checklist_item_id": item.parent_checklist_item_id,
        "text": item.text,
        "url": item.url,
        "checked": item.checked,
        "position": item.position,
    }


@router.get("/lessons/{lesson_id}/checklist")
def lesson_checklist(lesson_id: int,
                     session: Session = Depends(get_session)) -> list[dict]:
    from .. import checklist as service_checklist

    if session.get(Lesson, lesson_id) is None:
        raise HTTPException(404, "Lesson not found")
    return [_checklist_out(i) for i in service_checklist.for_lesson(session, lesson_id)]


@router.get("/notes/{note_id}/checklist")
def note_checklist(note_id: int,
                   session: Session = Depends(get_session)) -> list[dict]:
    from .. import checklist as service_checklist

    return [_checklist_out(i) for i in service_checklist.for_note(session, note_id)]


@router.patch("/checklist/{item_id}")
def toggle_checklist_item(item_id: int, payload: ChecklistToggle,
                          session: Session = Depends(get_session)) -> dict:
    """Tick a box from outside the note editor.

    The write lands on the note block and the projection follows — §2 forbids
    a divergent copy of the state.
    """
    from .. import checklist as service_checklist

    try:
        item = service_checklist.set_checked(session, item_id, payload.checked)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None

    if item.lesson_id and payload.checked:
        lesson = session.get(Lesson, item.lesson_id)
        if lesson is not None:
            service.sync_lesson_status(session, lesson)

    return _checklist_out(item)


# --------------------------------------------------------------------------
# Todos
# --------------------------------------------------------------------------

@router.get("/todos")
def list_todos(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(
        select(Todo).where(Todo.deleted_at.is_(None))
        .order_by(Todo.position, Todo.id)
    ).all()
    return [_todo_out(t) for t in rows]


@router.post("/todos", status_code=201)
def create_todo(payload: TodoCreate,
                session: Session = Depends(get_session)) -> dict:
    todo = Todo(
        title=payload.title.strip(),
        subject_id=payload.subject_id,
        topic_id=payload.topic_id,
        due_date=payload.due_date,
        position=_next_position(session, Todo),
    )
    session.add(todo)
    session.flush()
    return _todo_out(todo)


@router.patch("/todos/{todo_id}")
def update_todo(todo_id: int, payload: TodoUpdate,
                session: Session = Depends(get_session)) -> dict:
    todo = session.get(Todo, todo_id)
    if todo is None or todo.deleted_at is not None:
        raise HTTPException(404, "Todo not found")
    fields = payload.model_dump(exclude_unset=True)
    for field, value in fields.items():
        setattr(todo, field, value)
    if "done" in fields:
        todo.completed_at = _now() if fields["done"] else None
    todo.updated_at = _now()
    session.add(todo)
    session.flush()
    return _todo_out(todo)


@router.delete("/todos/{todo_id}", status_code=204)
def delete_todo(todo_id: int, session: Session = Depends(get_session)) -> None:
    todo = session.get(Todo, todo_id)
    if todo is None or todo.deleted_at is not None:
        raise HTTPException(404, "Todo not found")
    todo.deleted_at = _now()
    session.add(todo)


# --------------------------------------------------------------------------
# Links (addendum §2)
# --------------------------------------------------------------------------

def _link(session: Session, model, **keys) -> dict:
    existing = session.exec(
        select(model).where(*[getattr(model, k) == v for k, v in keys.items()])
    ).first()
    if existing is None:
        session.add(model(**keys))
        session.flush()
    return {"linked": True, **keys}


def _unlink(session: Session, model, **keys) -> None:
    row = session.exec(
        select(model).where(*[getattr(model, k) == v for k, v in keys.items()])
    ).first()
    if row is None:
        raise HTTPException(404, "Link not found")
    # A join row carries no user content, so removing it is not data loss.
    session.delete(row)
    session.flush()


@router.post("/notes/{note_id}/links/lessons/{lesson_id}")
def link_note_lesson(note_id: int, lesson_id: int,
                     session: Session = Depends(get_session)) -> dict:
    if session.get(Note, note_id) is None:
        raise HTTPException(404, "Note not found")
    if session.get(Lesson, lesson_id) is None:
        raise HTTPException(404, "Lesson not found")
    return _link(session, NoteLessonLink, note_id=note_id, lesson_id=lesson_id)


@router.delete("/notes/{note_id}/links/lessons/{lesson_id}", status_code=204)
def unlink_note_lesson(note_id: int, lesson_id: int,
                       session: Session = Depends(get_session)) -> None:
    _unlink(session, NoteLessonLink, note_id=note_id, lesson_id=lesson_id)


@router.post("/notes/{note_id}/links/resources/{resource_id}")
def link_note_resource(note_id: int, resource_id: int,
                       session: Session = Depends(get_session)) -> dict:
    if session.get(Note, note_id) is None:
        raise HTTPException(404, "Note not found")
    if session.get(Resource, resource_id) is None:
        raise HTTPException(404, "Resource not found")
    return _link(session, NoteResourceLink, note_id=note_id,
                 resource_id=resource_id)


@router.delete("/notes/{note_id}/links/resources/{resource_id}", status_code=204)
def unlink_note_resource(note_id: int, resource_id: int,
                         session: Session = Depends(get_session)) -> None:
    _unlink(session, NoteResourceLink, note_id=note_id, resource_id=resource_id)


@router.post("/lessons/{lesson_id}/links/resources/{resource_id}")
def link_lesson_resource(lesson_id: int, resource_id: int,
                         session: Session = Depends(get_session)) -> dict:
    if session.get(Lesson, lesson_id) is None:
        raise HTTPException(404, "Lesson not found")
    if session.get(Resource, resource_id) is None:
        raise HTTPException(404, "Resource not found")
    return _link(session, LessonResourceLink, lesson_id=lesson_id,
                 resource_id=resource_id)


@router.delete("/lessons/{lesson_id}/links/resources/{resource_id}",
               status_code=204)
def unlink_lesson_resource(lesson_id: int, resource_id: int,
                           session: Session = Depends(get_session)) -> None:
    _unlink(session, LessonResourceLink, lesson_id=lesson_id,
            resource_id=resource_id)


@router.get("/notes/{note_id}/links")
def note_links(note_id: int, session: Session = Depends(get_session)) -> dict:
    lessons = session.exec(
        select(NoteLessonLink).where(NoteLessonLink.note_id == note_id)
    ).all()
    resources = session.exec(
        select(NoteResourceLink).where(NoteResourceLink.note_id == note_id)
    ).all()
    return {
        "lessons": [
            {"lesson_id": l.lesson_id,
             "name": (session.get(Lesson, l.lesson_id).name
                      if session.get(Lesson, l.lesson_id) else None)}
            for l in lessons
        ],
        "resources": [
            {"resource_id": r.resource_id,
             "title": (session.get(Resource, r.resource_id).title
                       if session.get(Resource, r.resource_id) else None)}
            for r in resources
        ],
    }


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------

@router.get("/roadmap")
def roadmap(session: Session = Depends(get_session)) -> dict:
    return service.build_roadmap(session)


@router.get("/todos/board")
def board(subject_id: int | None = Query(default=None),
          topic_id: int | None = Query(default=None),
          has_due_date: bool | None = Query(default=None),
          hide_completed: bool = Query(default=True),
          session: Session = Depends(get_session)) -> dict:
    return service.todo_board(session, subject_id=subject_id,
                              topic_id=topic_id, has_due_date=has_due_date,
                              hide_completed=hide_completed)
