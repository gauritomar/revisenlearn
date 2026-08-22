"""Quick Practice endpoints (spec §15, §9.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .. import practice
from ..db import get_session
from ..models import MCQ, Concept

router = APIRouter()


def session_defaults(session: Session) -> dict:
    """Consolidated addendum §8 — `settings.session_defaults` was seeded but
    never read. It is the source of truth now, for both loops."""
    import json

    from ..models import Setting

    fallback = {"practice_count": 20, "revision_count": 5}
    row = session.get(Setting, "session_defaults")
    if row is None:
        return fallback
    try:
        value = json.loads(row.value_json)
    except json.JSONDecodeError:
        return fallback
    return {**fallback, **(value if isinstance(value, dict) else {})}


class SessionCreate(BaseModel):
    #: Spec §9.1 — "user picks a count (20 / 30 / 50 / custom)". `None` means
    #: "use whatever Settings says".
    count: int | None = Field(default=None, ge=1, le=200)
    scope: dict | None = None


class SessionOut(BaseModel):
    id: int
    planned_count: int
    completed_count: int
    correct_count: int


class AnswerIn(BaseModel):
    item_id: int
    selected_option_id: str
    response_ms: int | None = None


@router.get("/practice/defaults")
def defaults(session: Session = Depends(get_session)) -> dict:
    """What the count picker should offer and preselect."""
    values = session_defaults(session)
    preset = int(values["practice_count"])
    # Always offer the spec's three, plus whatever Settings says if it differs.
    options = sorted({20, 30, 50, preset})
    return {"default": preset, "options": options}


@router.get("/practice/available")
def available(session: Session = Depends(get_session)) -> dict:
    """How much there is to practise, so the picker can be honest about it."""
    pool = session.exec(
        select(MCQ).where(MCQ.status == "active", MCQ.deleted_at.is_(None))
    ).all()
    concepts = {m.concept_id for m in pool}
    return {
        "active_mcqs": len(pool),
        "concepts": len(concepts),
        "never_served": sum(1 for m in pool if m.times_served == 0),
    }


@router.post("/practice/session", response_model=SessionOut, status_code=201)
def create(payload: SessionCreate,
           session: Session = Depends(get_session)) -> SessionOut:
    scope = practice.Scope.from_payload(payload.scope)
    count = payload.count or int(session_defaults(session)["practice_count"])
    row = practice.create_session(session, count, scope)
    if row.planned_count == 0:
        raise HTTPException(409, "No active MCQs to practise yet")
    return SessionOut(id=row.id, planned_count=row.planned_count,
                      completed_count=0, correct_count=0)


@router.get("/practice/session/{session_id}/next")
def next_question(session_id: int,
                  session: Session = Depends(get_session)) -> dict:
    item = practice.next_item(session, session_id)
    if item is None:
        return {"done": True, "summary": practice.summary(session, session_id)}
    return {"done": False, "question": practice.serve(session, item)}


@router.post("/practice/session/{session_id}/answer")
def answer(session_id: int, payload: AnswerIn,
           session: Session = Depends(get_session)) -> dict:
    try:
        return practice.answer(session, session_id, payload.item_id,
                               payload.selected_option_id, payload.response_ms)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/practice/session/{session_id}/finish")
def finish(session_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        return practice.finish(session, session_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None


@router.get("/practice/session/{session_id}/summary")
def summary(session_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        return practice.summary(session, session_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None


@router.get("/practice/concepts/{concept_id}/mcqs")
def concept_pool(concept_id: int,
                 session: Session = Depends(get_session)) -> dict:
    """Pool health for one concept (§9.1 hygiene)."""
    from ..pipeline.mcqs import REGENERATE_BELOW, active_pool

    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, "Concept not found")
    pool = active_pool(session, concept_id)
    return {
        "concept_id": concept_id,
        "active": len(pool),
        "needs_regeneration": len(pool) < REGENERATE_BELOW,
        "floor": REGENERATE_BELOW,
    }
