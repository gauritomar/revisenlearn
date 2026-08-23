"""What to revise today, traced back to the day it was studied.

The user's ask: *"I wanted the spaced repetition algorithms to remind me that
today you have to revise what you studied 1/3/10 etc days ago. And I should
have their corresponding practice MCQ sets ready to open and practice."*

The intervals are not invented here. FSRS already decides when each concept
comes back (§9.3), and `review_items.due_at` is that decision. What was
missing is the other half of the sentence — *what you studied* — which lives
in `concept_sources`: the note block a concept came from, and therefore the
day it was written. Joining the two turns a flat due count into "the three
things you wrote on Tuesday are due today", which is the form a person can
act on.

Nothing here schedules anything. It reads what FSRS decided and groups it.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from .models import (
    MCQ,
    Concept,
    ConceptSource,
    MCQAttempt,
    Note,
    NoteBlock,
    ReviewItem,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _local_day(stamp: datetime | None) -> date | None:
    """The user's day, not UTC's."""
    if stamp is None:
        return None
    aware = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    return aware.astimezone().date()


def studied_on(session: Session) -> dict[int, date]:
    """concept id -> the day its earliest evidence was written.

    A concept can be drawn from several blocks over several days; the first is
    the one the user would call "when I studied it".
    """
    out: dict[int, date] = {}
    sources = session.exec(
        select(ConceptSource).where(ConceptSource.invalidated_at.is_(None))
    ).all()
    if not sources:
        return out

    block_ids = {s.note_block_id for s in sources}
    blocks = {
        b.id: b for b in session.exec(
            select(NoteBlock).where(NoteBlock.id.in_(block_ids))
        ).all()
    }
    notes = {
        n.id: n for n in session.exec(
            select(Note).where(Note.id.in_({b.note_id for b in blocks.values()}))
        ).all()
    }

    for source in sources:
        block = blocks.get(source.note_block_id)
        if block is None:
            continue
        # The day it was written, falling back to the note's own study date
        # for blocks that predate block timestamps.
        day = _local_day(block.created_at)
        if day is None:
            note = notes.get(block.note_id)
            day = note.study_date if note else None
        if day is None:
            continue
        current = out.get(source.concept_id)
        if current is None or day < current:
            out[source.concept_id] = day
    return out


def mcq_progress(session: Session, concept_ids: set[int]) -> dict[int, dict]:
    """Answered/correct per concept, so progress sits next to the work."""
    if not concept_ids:
        return {}
    mcqs = session.exec(
        select(MCQ).where(MCQ.concept_id.in_(concept_ids))
    ).all()
    by_mcq = {m.id: m.concept_id for m in mcqs}
    available: dict[int, int] = defaultdict(int)
    for mcq in mcqs:
        if mcq.deleted_at is None and mcq.status == "active":
            available[mcq.concept_id] += 1

    answered: dict[int, int] = defaultdict(int)
    correct: dict[int, int] = defaultdict(int)
    if by_mcq:
        for attempt in session.exec(
            select(MCQAttempt).where(MCQAttempt.mcq_id.in_(set(by_mcq)))
        ).all():
            concept_id = by_mcq.get(attempt.mcq_id)
            if concept_id is None:
                continue
            answered[concept_id] += 1
            correct[concept_id] += 1 if attempt.is_correct else 0

    return {
        cid: {
            "mcqs_available": available.get(cid, 0),
            "answered": answered.get(cid, 0),
            "correct": correct.get(cid, 0),
            "accuracy": (round(100 * correct[cid] / answered[cid])
                         if answered.get(cid) else None),
        }
        for cid in concept_ids
    }


def due_by_study_day(session: Session, now: datetime | None = None) -> dict:
    """Everything due now, grouped by the day it was studied.

    Each group carries the concepts, how long ago that was, whether there are
    MCQs ready, and how the MCQs have gone so far.
    """
    now = now or _now()
    today = now.astimezone().date()

    items = session.exec(
        select(ReviewItem).where(ReviewItem.suspended.is_(False))
    ).all()

    due_concepts: set[int] = set()
    for item in items:
        if item.due_at is None:
            due_concepts.add(item.concept_id)          # never reviewed: due now
            continue
        due = item.due_at if item.due_at.tzinfo else item.due_at.replace(tzinfo=timezone.utc)
        if due <= now:
            due_concepts.add(item.concept_id)

    if not due_concepts:
        return {"today": today.isoformat(), "groups": [], "total_due": 0}

    concepts = {
        c.id: c for c in session.exec(
            select(Concept).where(Concept.id.in_(due_concepts),
                                  Concept.deleted_at.is_(None))
        ).all()
    }
    studied = studied_on(session)
    progress = mcq_progress(session, set(concepts))

    grouped: dict[date | None, list[int]] = defaultdict(list)
    for concept_id in concepts:
        grouped[studied.get(concept_id)].append(concept_id)

    groups = []
    for day, ids in grouped.items():
        stats = [progress.get(cid, {}) for cid in ids]
        answered = sum(s.get("answered", 0) for s in stats)
        correct = sum(s.get("correct", 0) for s in stats)
        groups.append({
            "studied_on": day.isoformat() if day else None,
            "days_ago": (today - day).days if day else None,
            "concept_ids": sorted(ids),
            "concepts": [
                {"id": cid, "name": concepts[cid].canonical_name,
                 **progress.get(cid, {})}
                for cid in sorted(ids, key=lambda c: concepts[c].canonical_name)
            ],
            "due_count": len(ids),
            "mcqs_available": sum(s.get("mcqs_available", 0) for s in stats),
            "answered": answered,
            "correct": correct,
            "accuracy": round(100 * correct / answered) if answered else None,
        })

    # Oldest material first: the thing studied ten days ago is the thing
    # closest to being forgotten.
    groups.sort(key=lambda g: (g["days_ago"] is None, -(g["days_ago"] or 0)))
    return {"today": today.isoformat(), "groups": groups,
            "total_due": len(due_concepts)}


def upcoming_by_day(session: Session, first: date, last: date,
                    now: datetime | None = None) -> dict[str, int]:
    """How many concepts fall due on each day in a range, for the calendar."""
    now = now or _now()
    today = now.astimezone().date()
    counts: dict[str, int] = defaultdict(int)

    for item in session.exec(
        select(ReviewItem).where(ReviewItem.suspended.is_(False))
    ).all():
        day = _local_day(item.due_at) or today   # never reviewed: due now
        if day < today:
            day = today                          # overdue shows as today's work
        if first <= day < last:
            counts[day.isoformat()] += 1
    return dict(counts)


def study_days(session: Session, days: int = 30,
               now: datetime | None = None) -> list[dict]:
    """Recent days that produced concepts, with when each comes back.

    This is the retrospective half: "what you studied N days ago", whether or
    not it is due yet, so the calendar can show the shape of a week.
    """
    now = now or _now()
    today = now.astimezone().date()
    horizon = today - timedelta(days=days)

    studied = studied_on(session)
    by_day: dict[date, list[int]] = defaultdict(list)
    for concept_id, day in studied.items():
        if day >= horizon:
            by_day[day].append(concept_id)

    items = {i.concept_id: i for i in session.exec(select(ReviewItem)).all()}
    out = []
    for day, ids in sorted(by_day.items(), reverse=True):
        due_now = 0
        for concept_id in ids:
            item = items.get(concept_id)
            if item is None:
                continue
            due = _local_day(item.due_at)
            if due is None or due <= today:
                due_now += 1
        out.append({
            "date": day.isoformat(),
            "days_ago": (today - day).days,
            "concept_ids": sorted(ids),
            "concept_count": len(ids),
            "due_now": due_now,
        })
    return out
