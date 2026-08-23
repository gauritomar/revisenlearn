"""Coverage, review items, MCQs and Quick Practice (spec §9.1, §10 **[LOCKED]**).

Phase 6 is *done when* "the user can do a 50-MCQ session end to end" (§18).
All generation runs against the mock provider.
"""

from __future__ import annotations

import datetime as dt
import json
import random

import pytest
from sqlmodel import select

from revisenlearn import practice
from revisenlearn.pipeline.mcqs import MCQ_PROMPT_VERSION
from revisenlearn.llm import set_provider
from revisenlearn.llm.mock import MockProvider
from revisenlearn.models import (
    MCQ,
    Concept,
    MCQAttempt,
    Note,
    NoteBlock,
    ReviewItem,
    Subject,
    Subtopic,
    Topic,
)


@pytest.fixture(autouse=True)
def mock_llm():
    provider = MockProvider()
    set_provider(provider)
    yield provider
    set_provider(None)


def _subject(session, name="GenAI") -> Subject:
    row = Subject(name=name)
    session.add(row)
    session.flush()
    return row


def _concept(session, subject, name="Hybrid search", profile=None) -> Concept:
    concept = Concept(
        canonical_name=name,
        normalised_name=name.lower(),
        definition=f"{name} definition.",
        subject_id=subject.id,
        difficulty=3.0,
        coverage_profile_json=json.dumps(profile) if profile else None,
    )
    session.add(concept)
    session.flush()
    return concept


def _mcqs(session, concept, n=10, active=True) -> list[MCQ]:
    rows = []
    for i in range(n):
        mcq = MCQ(
            concept_id=concept.id,
            dimension="recall",
            stem=f"Q{i} about {concept.canonical_name}?",
            options_json=json.dumps([
                {"id": "a", "text": "right"}, {"id": "b", "text": "wrong"},
                {"id": "c", "text": "wrong"}, {"id": "d", "text": "wrong"},
            ]),
            correct_option_id="a",
            explanation="Because a.",
            status="active" if active else "retired",
        )
        session.add(mcq)
        rows.append(mcq)
    session.flush()
    return rows


# --------------------------------------------------------------------------
# §10.2 Coverage profiles and review items
# --------------------------------------------------------------------------

def test_a_review_item_is_created_per_enabled_dimension(session) -> None:
    from revisenlearn.pipeline.coverage import ensure_review_items

    subject = _subject(session)
    concept = _concept(session, subject, profile={
        "recall": True, "explain": True, "apply": True,
        "debug": False, "synthesis": False, "interview": True,
    })

    ensure_review_items(session, concept)

    items = {i.dimension: i for i in session.exec(
        select(ReviewItem).where(ReviewItem.concept_id == concept.id)).all()}
    assert set(items) == {"recall", "explain", "apply", "interview"}
    # "No review_item means no scheduling and no cost."
    assert "debug" not in items
    assert "synthesis" not in items


def test_interview_items_are_created_but_suspended(session) -> None:
    """Spec §10.1 — "review items are created but suspended". Default off."""
    from revisenlearn.pipeline.coverage import ensure_review_items

    subject = _subject(session)
    concept = _concept(session, subject, profile={
        "recall": True, "explain": False, "apply": False,
        "debug": False, "synthesis": False, "interview": True,
    })

    ensure_review_items(session, concept)

    items = {i.dimension: i for i in session.exec(
        select(ReviewItem).where(ReviewItem.concept_id == concept.id)).all()}
    assert items["interview"].suspended is True
    assert items["recall"].suspended is False


def test_creating_review_items_is_idempotent(session) -> None:
    from revisenlearn.pipeline.coverage import ensure_review_items

    subject = _subject(session)
    concept = _concept(session, subject, profile={
        "recall": True, "explain": True, "apply": False,
        "debug": False, "synthesis": False, "interview": False,
    })

    ensure_review_items(session, concept)
    second = ensure_review_items(session, concept)

    assert second == []
    assert len(session.exec(
        select(ReviewItem).where(ReviewItem.concept_id == concept.id)).all()) == 2


def test_a_concept_without_a_profile_gets_a_sensible_fallback(session) -> None:
    from revisenlearn.pipeline.coverage import ensure_review_items, read_profile

    subject = _subject(session)
    concept = _concept(session, subject)

    assert read_profile(concept)["recall"] is True
    ensure_review_items(session, concept)
    dims = {i.dimension for i in session.exec(select(ReviewItem)).all()}
    assert dims == {"recall", "explain"}


# --------------------------------------------------------------------------
# §9.1 MCQ generation and pool hygiene
# --------------------------------------------------------------------------

def test_ten_mcqs_are_generated_per_concept(session) -> None:
    from revisenlearn.pipeline.mcqs import generate_for_concept

    subject = _subject(session)
    concept = _concept(session, subject)

    stored = generate_for_concept(session, concept)

    assert stored == 10
    pool = session.exec(select(MCQ).where(MCQ.concept_id == concept.id)).all()
    assert len(pool) == 10
    for mcq in pool:
        options = json.loads(mcq.options_json)
        assert len(options) == 4
        assert mcq.correct_option_id in {o["id"] for o in options}
        assert mcq.explanation
        assert mcq.prompt_version == MCQ_PROMPT_VERSION
        assert mcq.status == "active"


def test_generation_is_logged_against_the_concept(session) -> None:
    """§1.6 — every call logged, and §12.6 wants cost per concept."""
    from revisenlearn.models import LLMRun
    from revisenlearn.pipeline.mcqs import generate_for_concept
    from revisenlearn.seed import seed_settings

    seed_settings(session)
    subject = _subject(session)
    concept = _concept(session, subject)

    generate_for_concept(session, concept)

    run = session.exec(select(LLMRun)).one()
    assert run.task == "mcq_generation"
    assert run.concept_id == concept.id
    assert run.model == "gemini-3.5-flash-lite"
    assert run.prompt_version == MCQ_PROMPT_VERSION
    assert run.estimated_cost_usd is not None


def test_an_incoherent_question_is_dropped(session, mock_llm) -> None:
    from revisenlearn.pipeline.mcqs import generate_for_concept

    subject = _subject(session)
    concept = _concept(session, subject)
    good = {
        "stem": "A real question?",
        "options": [{"id": "a", "text": "1"}, {"id": "b", "text": "2"},
                    {"id": "c", "text": "3"}, {"id": "d", "text": "4"}],
        "correct_option_id": "a", "explanation": "Because.",
        "distractor_rationales": {}, "dimension": "recall", "difficulty": 3,
    }
    bad = {**good, "stem": "Answer not among the options?",
           "correct_option_id": "z"}
    mock_llm.responses = [{"questions": [good, bad]}]

    stored = generate_for_concept(session, concept)

    assert stored == 1
    assert session.exec(select(MCQ)).one().stem == "A real question?"


def test_an_mcq_retires_after_three_consecutive_correct(session) -> None:
    """Spec §9.1 pool hygiene."""
    subject = _subject(session)
    concept = _concept(session, subject)
    mcq = _mcqs(session, concept, n=1)[0]

    row = practice.create_session(session, count=1)
    for _ in range(3):
        item = practice.next_item(session, row.id)
        if item is None:
            row = practice.create_session(session, count=1)
            item = practice.next_item(session, row.id)
        practice.serve(session, item)
        practice.answer(session, row.id, item.id, "a")

    session.refresh(mcq)
    assert mcq.consecutive_correct >= 3
    assert mcq.status == "retired"
    assert mcq.retired_at is not None


def test_a_wrong_answer_resets_the_streak(session) -> None:
    subject = _subject(session)
    concept = _concept(session, subject)
    mcq = _mcqs(session, concept, n=1)[0]

    row = practice.create_session(session, count=1)
    item = practice.next_item(session, row.id)
    practice.serve(session, item)
    practice.answer(session, row.id, item.id, "a")
    session.refresh(mcq)
    assert mcq.consecutive_correct == 1

    row2 = practice.create_session(session, count=1)
    item2 = practice.next_item(session, row2.id)
    practice.serve(session, item2)
    practice.answer(session, row2.id, item2.id, "b")

    session.refresh(mcq)
    assert mcq.consecutive_correct == 0
    assert mcq.status == "active"


def test_a_thin_pool_is_flagged_for_regeneration(session) -> None:
    from revisenlearn.pipeline.mcqs import needs_regeneration, retired_stems

    subject = _subject(session)
    concept = _concept(session, subject)
    pool = _mcqs(session, concept, n=5)

    assert needs_regeneration(session, concept.id) is False

    for mcq in pool[:2]:
        mcq.status = "retired"
        session.add(mcq)
    session.flush()

    assert needs_regeneration(session, concept.id) is True
    # Regeneration is seeded with what has already been asked (§9.1).
    assert len(retired_stems(session, concept.id)) == 2


def test_regeneration_avoids_repeating_a_stem(session) -> None:
    from revisenlearn.pipeline.mcqs import generate_for_concept

    subject = _subject(session)
    concept = _concept(session, subject)
    generate_for_concept(session, concept)
    first_stems = {m.stem for m in session.exec(select(MCQ)).all()}

    # A second run offers the same stems; none should be stored twice.
    generate_for_concept(session, concept)

    all_stems = [m.stem for m in session.exec(select(MCQ)).all()]
    assert len(all_stems) == len(set(all_stems)) == len(first_stems)


# --------------------------------------------------------------------------
# §9.1 Session composition
# --------------------------------------------------------------------------

def test_composition_is_forty_forty_twenty(session) -> None:
    subject = _subject(session)
    # 40 never-served, 40 previously failed, 40 previously correct.
    fresh = _concept(session, subject, "Fresh")
    failed = _concept(session, subject, "Failed")
    seen = _concept(session, subject, "Seen")
    _mcqs(session, fresh, n=40)
    failed_mcqs = _mcqs(session, failed, n=40)
    seen_mcqs = _mcqs(session, seen, n=40)

    now = dt.datetime(2026, 8, 22, 12, 0, tzinfo=dt.timezone.utc)
    for mcq in failed_mcqs:
        mcq.times_served = 1
        mcq.last_served_at = now
        session.add(mcq)
        session.add(MCQAttempt(mcq_id=mcq.id, concept_id=failed.id,
                               selected_option_id="b", is_correct=False,
                               created_at=now))
    for mcq in seen_mcqs:
        mcq.times_served = 1
        mcq.last_served_at = now - dt.timedelta(days=1)
        session.add(mcq)
        session.add(MCQAttempt(mcq_id=mcq.id, concept_id=seen.id,
                               selected_option_id="a", is_correct=True,
                               created_at=now))
    session.flush()

    chosen = practice.select_questions(session, 50, rng=random.Random(0))

    assert len(chosen) == 50
    by_concept = {"Fresh": 0, "Failed": 0, "Seen": 0}
    names = {fresh.id: "Fresh", failed.id: "Failed", seen.id: "Seen"}
    for mcq in chosen:
        by_concept[names[mcq.concept_id]] += 1

    assert by_concept["Fresh"] == 20     # 40% new
    assert by_concept["Failed"] == 20    # 40% failed
    assert by_concept["Seen"] == 10      # 20% random


def test_a_short_bucket_redistributes_into_random(session) -> None:
    """"If a bucket is short, redistribute into random. Sessions always fill
    to the requested count"."""
    subject = _subject(session)
    concept = _concept(session, subject)
    pool = _mcqs(session, concept, n=30)
    # Everything has been served and answered correctly: no new, no failed.
    for mcq in pool:
        mcq.times_served = 2
        mcq.last_served_at = dt.datetime(2026, 8, 21, tzinfo=dt.timezone.utc)
        session.add(mcq)
        session.add(MCQAttempt(mcq_id=mcq.id, concept_id=concept.id,
                               selected_option_id="a", is_correct=True))
    session.flush()

    chosen = practice.select_questions(session, 20, rng=random.Random(1))

    assert len(chosen) == 20


def test_a_session_never_repeats_a_question(session) -> None:
    subject = _subject(session)
    concept = _concept(session, subject)
    _mcqs(session, concept, n=25)

    chosen = practice.select_questions(session, 20, rng=random.Random(2))

    assert len({m.id for m in chosen}) == len(chosen) == 20


def test_a_session_is_capped_by_the_pool(session) -> None:
    subject = _subject(session)
    concept = _concept(session, subject)
    _mcqs(session, concept, n=3)

    chosen = practice.select_questions(session, 50)
    assert len(chosen) == 3


def test_retired_questions_are_never_served(session) -> None:
    subject = _subject(session)
    concept = _concept(session, subject)
    _mcqs(session, concept, n=5, active=False)

    assert practice.select_questions(session, 10) == []


def test_scope_limits_a_session_to_a_subject(session) -> None:
    genai = _subject(session, "GenAI")
    systems = _subject(session, "Systems")
    _mcqs(session, _concept(session, genai, "Hybrid search"), n=10)
    _mcqs(session, _concept(session, systems, "B-trees"), n=10)

    scope = practice.Scope(subject_ids=(genai.id,))
    chosen = practice.select_questions(session, 20, scope)

    assert len(chosen) == 10
    concept_ids = {m.concept_id for m in chosen}
    subjects = {session.get(Concept, cid).subject_id for cid in concept_ids}
    assert subjects == {genai.id}


# --------------------------------------------------------------------------
# Serving and answering
# --------------------------------------------------------------------------

def test_option_order_is_shuffled_every_serve(session) -> None:
    """Spec §9.1 — "shuffle option order every serve"."""
    subject = _subject(session)
    concept = _concept(session, subject)
    _mcqs(session, concept, n=1)

    orders = set()
    for seed in range(12):
        row = practice.create_session(session, count=1)
        item = practice.next_item(session, row.id)
        served = practice.serve(session, item, rng=random.Random(seed))
        orders.add(tuple(o["id"] for o in served["options"]))

    assert len(orders) > 1, "options were never shuffled"
    # Whatever the order, all four are always present.
    assert all(set(order) == {"a", "b", "c", "d"} for order in orders)


def test_answering_gives_instant_feedback_with_the_explanation(session) -> None:
    subject = _subject(session)
    concept = _concept(session, subject)
    _mcqs(session, concept, n=1)

    row = practice.create_session(session, count=1)
    item = practice.next_item(session, row.id)
    practice.serve(session, item)

    feedback = practice.answer(session, row.id, item.id, "b", response_ms=4200)

    assert feedback["is_correct"] is False
    assert feedback["correct_option_id"] == "a"
    assert feedback["explanation"] == "Because a."
    attempt = session.exec(select(MCQAttempt)).one()
    assert attempt.response_ms == 4200
    assert attempt.session_id == row.id


def test_a_question_cannot_be_answered_twice(session) -> None:
    subject = _subject(session)
    concept = _concept(session, subject)
    _mcqs(session, concept, n=1)

    row = practice.create_session(session, count=1)
    item = practice.next_item(session, row.id)
    practice.serve(session, item)
    practice.answer(session, row.id, item.id, "a")

    with pytest.raises(ValueError):
        practice.answer(session, row.id, item.id, "a")


def test_mcq_answers_never_touch_fsrs(session) -> None:
    """Spec §9.1 [LOCKED]: MCQ results "never touch FSRS state, never advance
    a due date, and never earn a mastery badge on their own. This is
    deliberate — recognition is not recall."
    """
    from revisenlearn.pipeline.coverage import ensure_review_items

    subject = _subject(session)
    concept = _concept(session, subject, profile={
        "recall": True, "explain": True, "apply": False,
        "debug": False, "synthesis": False, "interview": False,
    })
    ensure_review_items(session, concept)
    _mcqs(session, concept, n=3)

    before = [
        (i.id, i.fsrs_stability, i.due_at, i.reps, i.lapses,
         i.last_reviewed_at)
        for i in session.exec(select(ReviewItem)).all()
    ]

    row = practice.create_session(session, count=3)
    for _ in range(3):
        item = practice.next_item(session, row.id)
        practice.serve(session, item)
        practice.answer(session, row.id, item.id, "a")
    practice.finish(session, row.id)

    after = [
        (i.id, i.fsrs_stability, i.due_at, i.reps, i.lapses,
         i.last_reviewed_at)
        for i in session.exec(select(ReviewItem)).all()
    ]
    assert after == before

    # And nothing was written to the append-only review log.
    from revisenlearn.models import ReviewLog

    assert session.exec(select(ReviewLog)).all() == []


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

def test_the_summary_breaks_down_by_concept(session) -> None:
    subject = _subject(session)
    strong = _concept(session, subject, "Strong")
    weak = _concept(session, subject, "Weak")
    _mcqs(session, strong, n=2)
    _mcqs(session, weak, n=2)

    row = practice.create_session(session, count=4)
    for _ in range(4):
        item = practice.next_item(session, row.id)
        served = practice.serve(session, item)
        correct = served["concept_name"] == "Strong"
        practice.answer(session, row.id, item.id, "a" if correct else "b")

    result = practice.finish(session, row.id)

    assert result["completed_count"] == 4
    assert result["correct_count"] == 2
    assert result["duration_ms"] is not None
    by_name = {e["concept_name"]: e for e in result["per_concept"]}
    assert by_name["Strong"]["correct"] == 2
    assert by_name["Weak"]["correct"] == 0
    # Weakest first, so the summary leads with what to practise again.
    assert result["per_concept"][0]["concept_name"] == "Weak"
    # "practise the ones I missed" needs the ids.
    assert len(result["missed_mcq_ids"]) == 2


# --------------------------------------------------------------------------
# Phase 6's done-when, through the pipeline
# --------------------------------------------------------------------------

def test_a_pipeline_run_produces_concepts_review_items_and_mcqs(session) -> None:
    """Spec §19's smoke test, in full: "seed a note → run pipeline against a
    mocked provider → assert concepts, review items, and MCQs exist"."""
    from revisenlearn.db import session_scope
    from revisenlearn.hashing import content_hash
    from revisenlearn.pipeline.stages import create_job, run_job

    subject = _subject(session)
    topic = Topic(subject_id=subject.id, name="Retrieval")
    session.add(topic)
    session.flush()
    subtopic = Subtopic(topic_id=topic.id, name="Hybrid search")
    session.add(subtopic)
    session.flush()

    note = Note(title="Hybrid search", study_date=dt.date(2026, 8, 22),
                subject_id=subject.id, topic_id=topic.id,
                subtopic_id=subtopic.id)
    session.add(note)
    session.flush()
    for i, text in enumerate([
        "BM25 handles rare exact terms that dense embeddings routinely miss",
        "Reciprocal rank fusion merges the two rankings without tuning weights",
    ]):
        session.add(NoteBlock(note_id=note.id, position=i,
                              block_type="bullet_list_item", text=text,
                              content_hash=content_hash(text)))
    job = create_job(session)
    session.commit()

    assert run_job(job.id) == "succeeded"

    with session_scope() as s:
        concepts = [c for c in s.exec(select(Concept)).all()
                    if c.deleted_at is None]
        assert concepts

        items = s.exec(select(ReviewItem)).all()
        assert items, "no review items were created"
        # §10.1 — interview items exist but are suspended.
        for item in items:
            if item.dimension == "interview":
                assert item.suspended is True

        mcqs = s.exec(select(MCQ)).all()
        assert mcqs, "no MCQs were generated"
        assert all(m.status == "active" for m in mcqs)

        from revisenlearn.models import PipelineJob

        finished = s.get(PipelineJob, job.id)
        assert finished.mcqs_generated == len(mcqs)


def test_a_fifty_question_session_runs_end_to_end(session) -> None:
    """Phase 6 is done when "the user can do a 50-MCQ session end to end"."""
    subject = _subject(session)
    for n in range(6):
        _mcqs(session, _concept(session, subject, f"Concept {n}"), n=10)

    row = practice.create_session(session, count=50)
    assert row.planned_count == 50

    answered = 0
    while True:
        item = practice.next_item(session, row.id)
        if item is None:
            break
        served = practice.serve(session, item)
        assert served["stem"]
        assert len(served["options"]) == 4
        practice.answer(session, row.id, item.id,
                        "a" if answered % 2 == 0 else "b",
                        response_ms=1500)
        answered += 1

    assert answered == 50
    result = practice.finish(session, row.id)
    assert result["completed_count"] == 50
    assert result["correct_count"] == 25
    assert result["finished"] is True


def test_generation_is_grounded_in_the_learners_own_notes(session, mock_llm) -> None:
    """mcq_generation v2 — "a question generated from a definition is a
    question about a definition". The request carries the note text the
    concept came from, and the subject it sits under."""
    from revisenlearn.models import ConceptSource, Note, NoteBlock, Subject
    from revisenlearn.pipeline import mcqs

    subject = Subject(name="DSA")
    session.add(subject)
    session.flush()

    note = Note(title="Strings", study_date=dt.date.today(), subject_id=subject.id)
    session.add(note)
    session.flush()
    block = NoteBlock(
        note_id=note.id, position=0, block_type="bullet_list_item",
        text="Compare the current character with the next to decide add or subtract.",
        content_hash="h1",
    )
    session.add(block)
    session.flush()

    concept = Concept(canonical_name="Roman numerals",
                      normalised_name="roman numerals",
                      definition="Subtract when a smaller value precedes a larger one.",
                      subject_id=subject.id)
    session.add(concept)
    session.flush()
    session.add(ConceptSource(concept_id=concept.id, note_block_id=block.id,
                              note_id=note.id))
    session.flush()

    mcqs.generate_for_concept(session, concept)

    sent = mock_llm.calls[-1]["input"]
    assert "SUBJECT: DSA" in sent
    assert "NOTES:" in sent
    assert "Compare the current character with the next" in sent
