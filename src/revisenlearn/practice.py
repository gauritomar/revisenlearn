"""Quick Practice (spec §9.1 **[LOCKED]**).

```
40%  new         concepts never practised, or MCQs never served
40%  failed      MCQs answered incorrectly, most recent first
20%  random      anything else active, weighted toward least-recently-served
```

"If a bucket is short, redistribute into `random`. Sessions always fill to the
requested count."

**Effect on scheduling:** MCQ results feed practice statistics and the `recall`
mastery component only. "They never touch FSRS state, never advance a due date,
and never earn a mastery badge on their own. This is deliberate — recognition
is not recall."
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session, select

from .models import MCQ, Concept, MCQAttempt, Session as SessionRow, SessionItem
from .pipeline.mcqs import retire_if_exhausted

log = logging.getLogger(__name__)

#: Spec §9.1
NEW_SHARE = 0.40
FAILED_SHARE = 0.40


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Scope:
    """"all, or specific subjects/topics/tags" (§9.1)."""

    subject_ids: tuple[int, ...] = ()
    topic_ids: tuple[int, ...] = ()

    def to_json(self) -> str:
        return json.dumps({"subject_ids": list(self.subject_ids),
                           "topic_ids": list(self.topic_ids)})

    @classmethod
    def from_payload(cls, payload: dict | None) -> "Scope":
        payload = payload or {}
        return cls(
            subject_ids=tuple(payload.get("subject_ids") or ()),
            topic_ids=tuple(payload.get("topic_ids") or ()),
        )


def _scoped_concept_ids(session: Session, scope: Scope) -> set[int] | None:
    """None means "everything"."""
    if not scope.subject_ids and not scope.topic_ids:
        return None
    stmt = select(Concept).where(Concept.deleted_at.is_(None))
    if scope.subject_ids:
        stmt = stmt.where(Concept.subject_id.in_(scope.subject_ids))
    if scope.topic_ids:
        stmt = stmt.where(Concept.topic_id.in_(scope.topic_ids))
    return {c.id for c in session.exec(stmt).all()}


def _active_mcqs(session: Session, scope: Scope) -> list[MCQ]:
    allowed = _scoped_concept_ids(session, scope)
    rows = session.exec(
        select(MCQ).where(MCQ.status == "active", MCQ.deleted_at.is_(None))
    ).all()
    if allowed is None:
        return list(rows)
    return [m for m in rows if m.concept_id in allowed]


def select_questions(session: Session, count: int,
                     scope: Scope | None = None,
                     rng: random.Random | None = None) -> list[MCQ]:
    """Build a session per §9.1's 40/40/20, filling short buckets from random."""
    rng = rng or random.Random()
    scope = scope or Scope()
    pool = _active_mcqs(session, scope)
    if not pool:
        return []

    by_id = {m.id: m for m in pool}

    # --- failed: answered incorrectly, most recent first -------------------
    attempts = session.exec(
        select(MCQAttempt).order_by(MCQAttempt.created_at.desc())
    ).all()
    failed_ids: list[int] = []
    seen_failed: set[int] = set()
    answered_ids: set[int] = set()
    for attempt in attempts:
        answered_ids.add(attempt.mcq_id)
        if attempt.is_correct or attempt.mcq_id in seen_failed:
            continue
        if attempt.mcq_id in by_id:
            seen_failed.add(attempt.mcq_id)
            failed_ids.append(attempt.mcq_id)

    # --- new: never served -------------------------------------------------
    new_pool = [m for m in pool if m.times_served == 0 and m.id not in seen_failed]
    rng.shuffle(new_pool)

    # --- random: everything else, least-recently-served first --------------
    chosen: list[MCQ] = []
    used: set[int] = set()

    def take(candidates: list[MCQ], limit: int) -> None:
        for mcq in candidates:
            if len(chosen) >= count or limit <= 0:
                return
            if mcq.id in used:
                continue
            used.add(mcq.id)
            chosen.append(mcq)
            limit -= 1

    take(new_pool, round(count * NEW_SHARE))
    take([by_id[i] for i in failed_ids], round(count * FAILED_SHARE))

    # --- random: "anything else active, weighted toward least-recently-served"
    #
    # "Anything else" means anything the other two buckets have not claimed:
    # not never-served (that is `new`), not currently-failed (that is
    # `failed`). Letting their leftovers back in here would quietly collapse
    # 40/40/20 into "mostly whichever bucket is largest".
    remaining = count - len(chosen)
    eligible = [
        m for m in pool
        if m.id not in used and m.times_served > 0 and m.id not in seen_failed
    ]
    eligible.sort(key=lambda m: (
        m.last_served_at or datetime.min.replace(tzinfo=timezone.utc),
        m.times_served,
    ))
    take(eligible, remaining)

    # Only once that is exhausted do the other buckets' leftovers fill the gap
    # — §9.1 requires sessions to "always fill to the requested count".
    if len(chosen) < count:
        leftovers = [m for m in pool if m.id not in used]
        leftovers.sort(key=lambda m: (
            m.last_served_at or datetime.min.replace(tzinfo=timezone.utc),
            m.times_served,
        ))
        take(leftovers, count - len(chosen))

    return chosen[:count]


def bucket_of(session: Session, mcq: MCQ) -> str:
    if mcq.times_served == 0:
        return "new"
    last_wrong = session.exec(
        select(MCQAttempt)
        .where(MCQAttempt.mcq_id == mcq.id)
        .order_by(MCQAttempt.created_at.desc())
    ).first()
    if last_wrong is not None and not last_wrong.is_correct:
        return "failed"
    return "random"


def create_session(session: Session, count: int, scope: Scope | None = None,
                   rng: random.Random | None = None) -> SessionRow:
    scope = scope or Scope()
    questions = select_questions(session, count, scope, rng)

    row = SessionRow(
        session_type="practice",
        scope_json=scope.to_json(),
        planned_count=len(questions),
        started_at=_now(),
    )
    session.add(row)
    session.flush()

    for position, mcq in enumerate(questions):
        session.add(SessionItem(
            session_id=row.id,
            position=position,
            item_type="mcq",
            mcq_id=mcq.id,
            selection_bucket=bucket_of(session, mcq),
        ))
    session.flush()
    return row


def next_item(session: Session, session_id: int) -> SessionItem | None:
    return session.exec(
        select(SessionItem)
        .where(SessionItem.session_id == session_id,
               SessionItem.answered_at.is_(None))
        .order_by(SessionItem.position)
    ).first()


def serve(session: Session, item: SessionItem,
          rng: random.Random | None = None) -> dict:
    """Spec §9.1 — "shuffle option order every serve"."""
    rng = rng or random.Random()
    mcq = session.get(MCQ, item.mcq_id)
    if mcq is None:
        raise LookupError("MCQ missing")

    options = json.loads(mcq.options_json)
    rng.shuffle(options)

    if item.served_at is None:
        item.served_at = _now()
        mcq.times_served += 1
        mcq.last_served_at = _now()
        session.add_all([item, mcq])
        session.flush()

    concept = session.get(Concept, mcq.concept_id)
    return {
        "item_id": item.id,
        "position": item.position,
        "mcq_id": mcq.id,
        "concept_id": mcq.concept_id,
        "concept_name": concept.canonical_name if concept else "",
        "dimension": mcq.dimension,
        "stem": mcq.stem,
        "options": options,
        "selection_bucket": item.selection_bucket,
    }


def answer(session: Session, session_id: int, item_id: int,
           selected_option_id: str, response_ms: int | None = None) -> dict:
    """Record an answer and give instant feedback with the explanation.

    Writes `mcq_attempts` only. FSRS is not touched — §9.1 is explicit that
    recognition is not recall.
    """
    item = session.get(SessionItem, item_id)
    if item is None or item.session_id != session_id:
        raise LookupError("Session item not found")
    if item.answered_at is not None:
        raise ValueError("That question has already been answered")

    mcq = session.get(MCQ, item.mcq_id)
    if mcq is None:
        raise LookupError("MCQ missing")

    is_correct = selected_option_id == mcq.correct_option_id

    session.add(MCQAttempt(
        mcq_id=mcq.id,
        concept_id=mcq.concept_id,
        session_id=session_id,
        selected_option_id=selected_option_id,
        is_correct=is_correct,
        response_ms=response_ms,
    ))

    mcq.times_correct += 1 if is_correct else 0
    mcq.consecutive_correct = mcq.consecutive_correct + 1 if is_correct else 0
    session.add(mcq)

    item.answered_at = _now()
    session.add(item)

    row = session.get(SessionRow, session_id)
    if row is not None:
        row.completed_count += 1
        row.correct_count += 1 if is_correct else 0
        session.add(row)

    session.flush()
    retired = retire_if_exhausted(session, mcq)

    return {
        "is_correct": is_correct,
        "correct_option_id": mcq.correct_option_id,
        "explanation": mcq.explanation,
        "distractor_rationales": json.loads(mcq.distractor_rationale_json or "{}"),
        "retired": retired,
        "consecutive_correct": mcq.consecutive_correct,
    }


def finish(session: Session, session_id: int) -> dict:
    row = session.get(SessionRow, session_id)
    if row is None:
        raise LookupError("Session not found")
    if row.finished_at is None:
        row.finished_at = _now()
        started = row.started_at
        if started is not None:
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            row.duration_ms = int((row.finished_at - started).total_seconds() * 1000)
        session.add(row)
        session.flush()
    return summary(session, session_id)


def summary(session: Session, session_id: int) -> dict:
    """Spec §9.1 — "summary with per-concept breakdown and a 'practise the ones
    I missed' button"."""
    row = session.get(SessionRow, session_id)
    if row is None:
        raise LookupError("Session not found")

    attempts = session.exec(
        select(MCQAttempt).where(MCQAttempt.session_id == session_id)
    ).all()

    per_concept: dict[int, dict] = {}
    missed: list[int] = []
    for attempt in attempts:
        entry = per_concept.setdefault(attempt.concept_id, {
            "concept_id": attempt.concept_id, "concept_name": "",
            "asked": 0, "correct": 0,
        })
        entry["asked"] += 1
        entry["correct"] += 1 if attempt.is_correct else 0
        if not attempt.is_correct:
            missed.append(attempt.mcq_id)

    for concept_id, entry in per_concept.items():
        concept = session.get(Concept, concept_id)
        entry["concept_name"] = concept.canonical_name if concept else "(deleted)"

    return {
        "session_id": session_id,
        "planned_count": row.planned_count,
        "completed_count": row.completed_count,
        "correct_count": row.correct_count,
        "duration_ms": row.duration_ms,
        "finished": row.finished_at is not None,
        "per_concept": sorted(per_concept.values(),
                              key=lambda e: (e["correct"] / max(1, e["asked"]),
                                             e["concept_name"])),
        "missed_mcq_ids": missed,
    }
