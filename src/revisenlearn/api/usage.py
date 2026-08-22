"""Usage, mastery and progress (spec §12.6, §10.5, §14)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from .. import usage as service
from ..db import get_session
from ..models import Concept, MCQAttempt, QuestionAttempt, ReviewLog
from ..scheduling import concept_mastery

router = APIRouter()


@router.get("/usage/summary")
def summary(session: Session = Depends(get_session)) -> dict:
    return service.summary(session)


@router.get("/usage/by-concept")
def by_concept(limit: int = Query(default=100, ge=1, le=500),
               session: Session = Depends(get_session)) -> list[dict]:
    return service.by_concept(session, limit)


@router.get("/usage/by-task")
def by_task(session: Session = Depends(get_session)) -> list[dict]:
    return service.summary(session)["by_task"]


@router.get("/usage/by-hierarchy")
def by_hierarchy(session: Session = Depends(get_session)) -> dict:
    return service.by_hierarchy(session)


@router.get("/usage/cap")
def cap(session: Session = Depends(get_session)) -> dict:
    """The soft cap state. §12.6 — never a hard block."""
    return service.cap_state(session)


@router.get("/progress")
def progress(session: Session = Depends(get_session)) -> dict:
    """Spec §14 Dashboard Progress — "concepts, reviews, mastery distribution,
    retention over time. No streaks."
    """
    concepts = session.exec(
        select(Concept).where(Concept.deleted_at.is_(None))
    ).all()

    distribution = {"mastered": 0, "fading": 0, "learning": 0, "untested": 0}
    for concept in concepts:
        badge = concept_mastery(session, concept.id)["badge"]
        distribution[badge] = distribution.get(badge, 0) + 1

    logs = session.exec(select(ReviewLog)).all()
    by_day: dict[str, int] = {}
    for row in logs:
        if row.created_at:
            key = row.created_at.date().isoformat()
            by_day[key] = by_day.get(key, 0) + 1

    mcq_attempts = session.exec(select(MCQAttempt)).all()
    prose_attempts = session.exec(select(QuestionAttempt)).all()

    # The dashboard's "Due to review" was a Phase 7 placeholder long after
    # Phase 7 shipped; the number exists, so it is reported.
    from ..revision import dashboard as revision_dashboard

    due = revision_dashboard(session)

    return {
        "concepts": len(concepts),
        "due_today": due.get("due_count", 0),
        "stale_concepts": sum(1 for c in concepts if c.status == "stale"),
        "reviews": len(logs),
        "mcq_answers": len(mcq_attempts),
        "mcq_correct": sum(1 for a in mcq_attempts if a.is_correct),
        "prose_answers": len(prose_attempts),
        "mastery_distribution": distribution,
        # Cumulative totals over time, never a streak (§9.6, §14).
        "reviews_by_day": [
            {"date": day, "count": count}
            for day, count in sorted(by_day.items())
        ],
    }


@router.get("/concepts/{concept_id}/mastery")
def mastery(concept_id: int, session: Session = Depends(get_session)) -> dict:
    return concept_mastery(session, concept_id)


@router.post("/maintenance/adaptive-coverage")
def adaptive_coverage(session: Session = Depends(get_session)) -> dict:
    """Spec §10.2's adaptive pass. Exposed as an explicit action rather than a
    silent nightly job — §21.5 flags it as untested and possibly
    volume-inflating, and principle §1.3 says nothing is automatic."""
    from ..pipeline.coverage import adaptive_pass

    return adaptive_pass(session)
