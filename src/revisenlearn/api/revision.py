"""Revision endpoints (spec §15, §9.2–§9.6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from .. import revision
from ..db import get_session

router = APIRouter()


class SessionCreate(BaseModel):
    #: Spec §9.6 — default 5, not 10.
    count: int = Field(default=revision.DEFAULT_SESSION_SIZE, ge=1, le=100)
    subject_ids: list[int] | None = None


class AnswerIn(BaseModel):
    item_id: int
    answer: str = Field(min_length=1)
    response_ms: int | None = None


class SkipIn(BaseModel):
    item_id: int


class OverrideIn(BaseModel):
    attempt_id: int
    #: "got_it" -> one step up; "wrong" -> Again (§9.4).
    direction: str


class RetestStart(BaseModel):
    attempt_id: int
    mode: str = "same"


class RetestAnswer(BaseModel):
    question_id: int
    retest_of_attempt_id: int
    answer: str = Field(min_length=1)
    response_ms: int | None = None


@router.get("/revision/dashboard")
def dashboard(session: Session = Depends(get_session)) -> dict:
    return revision.dashboard(session)


@router.post("/revision/session", status_code=201)
def create(payload: SessionCreate,
           session: Session = Depends(get_session)) -> dict:
    row = revision.create_session(
        session, payload.count, tuple(payload.subject_ids or ())
    )
    if row.planned_count == 0:
        raise HTTPException(409, "Nothing is due yet")
    return {"id": row.id, "planned_count": row.planned_count}


@router.get("/revision/session/{session_id}/next")
def next_question(session_id: int,
                  session: Session = Depends(get_session)) -> dict:
    item = revision.next_item(session, session_id)
    if item is None:
        return {"done": True, "summary": revision.summary(session, session_id)}
    try:
        return {"done": False, "question": revision.serve(session, item)}
    except Exception as exc:
        # Spec §16 — "If the API is unavailable when a revision session is
        # started, say so plainly and offer Quick Practice instead."
        raise HTTPException(
            503,
            f"Could not write a question right now: {exc}. "
            "Quick Practice works offline.",
        ) from None


@router.post("/revision/session/{session_id}/answer")
def answer(session_id: int, payload: AnswerIn,
           session: Session = Depends(get_session)) -> dict:
    try:
        return revision.answer(session, session_id, payload.item_id,
                               payload.answer, payload.response_ms)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/revision/session/{session_id}/skip")
def skip(session_id: int, payload: SkipIn,
         session: Session = Depends(get_session)) -> dict:
    try:
        return revision.skip(session, session_id, payload.item_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/revision/session/{session_id}/override")
def override(session_id: int, payload: OverrideIn,
             session: Session = Depends(get_session)) -> dict:
    try:
        return revision.override(session, session_id, payload.attempt_id,
                                 payload.direction)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/revision/session/{session_id}/retest")
def retest(session_id: int, payload: RetestStart,
           session: Session = Depends(get_session)) -> dict:
    try:
        return revision.start_retest(session, session_id, payload.attempt_id,
                                     payload.mode)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/revision/session/{session_id}/retest/answer")
def retest_answer(session_id: int, payload: RetestAnswer,
                  session: Session = Depends(get_session)) -> dict:
    try:
        return revision.answer_retest(session, session_id, payload.question_id,
                                      payload.retest_of_attempt_id,
                                      payload.answer, payload.response_ms)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None


@router.post("/revision/session/{session_id}/finish")
def finish(session_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        return revision.finish(session, session_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
