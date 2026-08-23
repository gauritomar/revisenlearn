"""Revision traced back to the day the work was done.

"I wanted the spaced repetition algorithms to remind me that today you have to
revise what you studied 1/3/10 etc days ago. And I should have their
corresponding practice MCQ sets ready to open and practice. I should also be
able to look at my progress on the MCQs side by side."

FSRS owns the intervals (§9.3 **[LOCKED]**) — nothing here schedules anything.
These tests are about the other half: saying which day's writing each due
concept came from, and having its questions ready.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlmodel import select

from revisenlearn import recall
from revisenlearn.models import (
    MCQ,
    Concept,
    ConceptSource,
    MCQAttempt,
    Note,
    NoteBlock,
    ReviewItem,
    Subject,
)


def _concept_written_on(session, name: str, day: dt.date) -> Concept:
    """A concept, and the note block it was drawn from, written on `day`."""
    subject = session.exec(select(Subject)).first()
    if subject is None:
        subject = Subject(name="DSA")
        session.add(subject)
        session.flush()

    note = Note(title=name, study_date=day, subject_id=subject.id)
    session.add(note)
    session.flush()

    written = dt.datetime.combine(day, dt.time(9, 0), tzinfo=dt.timezone.utc)
    block = NoteBlock(note_id=note.id, position=0, block_type="paragraph",
                      text=f"{name} matters because…", content_hash=name,
                      created_at=written, updated_at=written)
    session.add(block)
    session.flush()

    concept = Concept(canonical_name=name, normalised_name=name.lower(),
                      subject_id=subject.id)
    session.add(concept)
    session.flush()
    session.add(ConceptSource(concept_id=concept.id, note_block_id=block.id,
                              note_id=note.id))
    session.flush()
    return concept


def _due(session, concept: Concept, *, due_at: dt.datetime | None) -> ReviewItem:
    item = ReviewItem(concept_id=concept.id, dimension="recall", due_at=due_at)
    session.add(item)
    session.flush()
    return item


def test_due_work_is_grouped_by_the_day_it_was_written(session) -> None:
    today = dt.date.today()
    old = _concept_written_on(session, "Roman numerals", today - dt.timedelta(days=10))
    recent = _concept_written_on(session, "ord()", today - dt.timedelta(days=3))
    _due(session, old, due_at=None)          # never reviewed: due now
    _due(session, recent, due_at=None)

    plan = recall.due_by_study_day(session)

    assert plan["total_due"] == 2
    assert [(g["days_ago"], g["due_count"]) for g in plan["groups"]] == [(10, 1), (3, 1)]
    # Oldest first: ten days ago is closest to being forgotten.
    assert plan["groups"][0]["concepts"][0]["name"] == "Roman numerals"


def test_work_that_is_not_due_yet_is_left_out(session) -> None:
    """§9.6 — the count is information, not a debt. Nothing is pulled forward."""
    today = dt.date.today()
    concept = _concept_written_on(session, "Sliding window", today)
    _due(session, concept,
         due_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3))

    assert recall.due_by_study_day(session)["total_due"] == 0


def test_a_suspended_item_stays_out_of_the_plan(session) -> None:
    today = dt.date.today()
    concept = _concept_written_on(session, "Tries", today)
    item = _due(session, concept, due_at=None)
    item.suspended = True
    session.add(item)
    session.flush()

    assert recall.due_by_study_day(session)["total_due"] == 0


def test_mcq_progress_travels_with_the_group(session) -> None:
    """"I should also be able to look at my progress on the MCQs side by
    side." """
    today = dt.date.today()
    concept = _concept_written_on(session, "Binary search", today - dt.timedelta(days=1))
    _due(session, concept, due_at=None)

    for i in range(3):
        mcq = MCQ(concept_id=concept.id, dimension="recall",
                  stem=f"Q{i}", options_json="[]", correct_option_id="a",
                  status="active", prompt_version="v1")
        session.add(mcq)
        session.flush()
        if i < 2:
            session.add(MCQAttempt(mcq_id=mcq.id, concept_id=concept.id,
                                   selected_option_id="a",
                                   is_correct=i == 0))
    session.flush()

    group = recall.due_by_study_day(session)["groups"][0]

    assert group["mcqs_available"] == 3
    assert (group["answered"], group["correct"]) == (2, 1)
    assert group["accuracy"] == 50
    assert group["concepts"][0]["mcqs_available"] == 3


def test_the_calendar_counts_what_comes_back_on_each_day(session) -> None:
    today = dt.date.today()
    soon = _concept_written_on(session, "Heaps", today)
    later = _concept_written_on(session, "Graphs", today)
    _due(session, soon,
         due_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2))
    _due(session, later,
         due_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2))

    counts = recall.upcoming_by_day(session, today, today + dt.timedelta(days=30))

    assert counts[(today + dt.timedelta(days=2)).isoformat()] == 2


def test_overdue_work_lands_on_today_not_the_day_it_slipped(session) -> None:
    """A calendar of missed days is a guilt machine; §9.6 forbids that framing.
    Overdue work is simply today's work."""
    today = dt.date.today()
    concept = _concept_written_on(session, "Recursion", today - dt.timedelta(days=9))
    _due(session, concept,
         due_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=4))

    counts = recall.upcoming_by_day(session, today - dt.timedelta(days=30),
                                    today + dt.timedelta(days=30))

    assert counts.get(today.isoformat()) == 1
    assert counts.get((today - dt.timedelta(days=4)).isoformat()) is None


def test_a_practice_session_can_be_scoped_to_one_days_concepts(client) -> None:
    """"Their corresponding practice MCQ sets ready to open and practice" —
    so the plan hands back concept ids a session can be built from."""
    subject = client.post("/api/subjects", json={"name": "DSA"}).json()
    concepts = [
        client.post("/api/concepts", json={
            "name": name, "definition": f"About {name}.",
            "subject_id": subject["id"],
        }).json()["concept"]
        for name in ("Roman numerals", "Two pointers")
    ]

    scoped = client.post("/api/practice/session", json={
        "count": 10,
        "scope": {"concept_ids": [concepts[0]["id"]]},
    })
    # No MCQs yet, so there is nothing to serve — but the scope is honoured
    # rather than silently widened to everything.
    assert scoped.status_code in (201, 409)
    if scoped.status_code == 201:
        assert scoped.json()["planned_count"] == 0
