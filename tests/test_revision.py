"""FSRS and the prose revision loop (spec §9.2–§9.6, §10 **[LOCKED]**).

"Prose review is the point of the app."

Phase 7 is *done when* "a full prose session runs, ratings land in FSRS, and
due dates move sensibly" (§18). Everything runs against the mock provider.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fsrs import Rating, State
from sqlmodel import select

from revisenlearn import revision, scheduling
from revisenlearn.llm import set_provider
from revisenlearn.llm.mock import MockProvider
from revisenlearn.models import (
    Concept,
    Misconception,
    Question,
    QuestionAttempt,
    ReviewItem,
    ReviewLog,
    Subject,
)
from revisenlearn.scheduling import Evaluation, derive_rating


@pytest.fixture(autouse=True)
def mock_llm():
    provider = MockProvider()
    set_provider(provider)
    yield provider
    set_provider(None)


def _concept(session, name="Hybrid search", importance=3.0) -> Concept:
    subject = session.exec(select(Subject)).first()
    if subject is None:
        subject = Subject(name="GenAI")
        session.add(subject)
        session.flush()
    concept = Concept(canonical_name=name, normalised_name=name.lower(),
                      definition=f"{name} definition.", subject_id=subject.id,
                      importance=importance, difficulty=3.0)
    session.add(concept)
    session.flush()
    return concept


def _item(session, concept, dimension="explain", **kwargs) -> ReviewItem:
    item = ReviewItem(concept_id=concept.id, dimension=dimension, **kwargs)
    session.add(item)
    session.flush()
    return item


#: The mock evaluator marks a key point hit when its first three words appear
#: in the answer, so these produce predictable hit ratios.
def _answer_hitting(question: Question, count: int) -> str:
    points = json.loads(question.key_points_json)
    return " ".join(" ".join(p.split()[:3]) for p in points[:count]) or "nothing"


# --------------------------------------------------------------------------
# §9.3 Deterministic rating
# --------------------------------------------------------------------------

def _evaluation(hits: int, total: int, wrong=(), misconceptions=()) -> Evaluation:
    return Evaluation(
        key_point_hits=[{"point": f"p{i}", "hit": i < hits} for i in range(total)],
        factually_incorrect_claims=list(wrong),
        misconceptions=list(misconceptions),
        feedback="",
    )


@pytest.mark.parametrize(
    "hits,total,expected",
    [
        (0, 5, Rating.Again),    # 0.0  < 0.4
        (1, 5, Rating.Again),    # 0.2  < 0.4
        (2, 5, Rating.Hard),     # 0.4  -> Hard
        (3, 5, Rating.Hard),     # 0.6  < 0.7
        (7, 10, Rating.Good),    # 0.7  -> Good
        (9, 10, Rating.Good),    # 0.9  < 0.95
        (20, 20, Rating.Easy),   # 1.0  >= 0.95
    ],
)
def test_rating_is_derived_from_the_hit_ratio(hits, total, expected) -> None:
    assert derive_rating(_evaluation(hits, total)) is expected


def test_any_incorrect_claim_forces_again() -> None:
    """Spec §9.3 — a factual error outranks the ratio, however good."""
    assert derive_rating(_evaluation(20, 20, wrong=["wrong"])) is Rating.Again


def test_any_misconception_forces_again() -> None:
    assert derive_rating(
        _evaluation(20, 20, misconceptions=["confused X with Y"])
    ) is Rating.Again


def test_the_models_suggested_rating_is_ignored() -> None:
    """"`suggested_rating` from the model is stored for comparison but not
    used"."""
    evaluation = Evaluation(
        key_point_hits=[{"point": "p", "hit": False}],
        factually_incorrect_claims=[], misconceptions=[],
        feedback="", suggested_rating="easy",
    )
    assert derive_rating(evaluation) is Rating.Again


# --------------------------------------------------------------------------
# §9.4 Override
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "start,expected",
    [(Rating.Again, Rating.Hard), (Rating.Hard, Rating.Good),
     (Rating.Good, Rating.Easy), (Rating.Easy, Rating.Easy)],
)
def test_i_actually_got_this_steps_one_up(start, expected) -> None:
    assert scheduling.apply_override(start, "got_it") is expected


@pytest.mark.parametrize("start", list(Rating))
def test_no_i_was_wrong_forces_again(start) -> None:
    assert scheduling.apply_override(start, "wrong") is Rating.Again


# --------------------------------------------------------------------------
# FSRS wiring
# --------------------------------------------------------------------------

def test_a_review_advances_fsrs_and_sets_a_due_date(session) -> None:
    concept = _concept(session)
    item = _item(session, concept)
    assert item.due_at is None

    scheduling.record_review(session, item, final_rating=Rating.Good)

    assert item.due_at is not None
    assert item.fsrs_stability and item.fsrs_stability > 0
    assert item.fsrs_difficulty and item.fsrs_difficulty > 0
    assert item.reps == 1
    assert item.lapses == 0


def test_again_counts_a_lapse_and_shortens_the_interval(session) -> None:
    concept = _concept(session)
    good = _item(session, concept, dimension="explain")
    bad = _item(session, concept, dimension="apply")

    scheduling.record_review(session, good, final_rating=Rating.Easy)
    scheduling.record_review(session, bad, final_rating=Rating.Again)

    assert bad.lapses == 1
    assert good.lapses == 0
    # Easy schedules further out than Again.
    assert good.due_at > bad.due_at


def test_review_logs_capture_before_and_after(session) -> None:
    """Spec §6 — review_logs is the evidence base for tuning §21's guesses."""
    concept = _concept(session)
    item = _item(session, concept)

    scheduling.record_review(session, item, final_rating=Rating.Good)
    first = session.exec(select(ReviewLog)).one()
    assert first.due_before is None
    assert first.due_after is not None
    assert first.stability_before is None
    assert first.stability_after is not None

    scheduling.record_review(session, item, final_rating=Rating.Good)
    logs = session.exec(select(ReviewLog).order_by(ReviewLog.id)).all()
    assert len(logs) == 2
    assert logs[1].stability_before == first.stability_after


def test_review_logs_are_append_only(session) -> None:
    """§6: "APPEND ONLY. No UPDATE, no DELETE, ever." An override is a new
    row, never an edit to the old one."""
    concept = _concept(session)
    item = _item(session, concept)
    scheduling.record_review(session, item, final_rating=Rating.Again,
                             evaluator_rating=Rating.Again)
    original = session.exec(select(ReviewLog)).one()
    original_id, original_rating = original.id, original.rating

    scheduling.record_review(session, item, final_rating=Rating.Good,
                             evaluator_rating=Rating.Again,
                             user_override_rating=Rating.Good)

    logs = session.exec(select(ReviewLog).order_by(ReviewLog.id)).all()
    assert len(logs) == 2
    assert logs[0].id == original_id
    assert logs[0].rating == original_rating          # untouched
    assert logs[1].user_override_rating == int(Rating.Good)


def test_mastery_decays_with_time_on_its_own(session) -> None:
    """Spec §10.5 — "Because freshness is FSRS retrievability, mastery decays
    automatically with time … no separate decay system"."""
    concept = _concept(session)
    item = _item(session, concept)

    now = dt.datetime(2026, 8, 22, 12, 0, tzinfo=dt.timezone.utc)
    for _ in range(3):
        scheduling.record_review(
            session, item, final_rating=Rating.Easy,
            evaluation=_evaluation(5, 5), now=now,
        )
        now += dt.timedelta(days=1)

    fresh = scheduling.mastery_of(session, item, now)
    later = scheduling.mastery_of(session, item, now + dt.timedelta(days=365))

    assert fresh.quality == 1.0
    assert fresh.badge == "mastered"
    assert later.freshness < fresh.freshness
    assert later.mastery < fresh.mastery
    # Quality is unchanged; only freshness decayed.
    assert later.quality == fresh.quality
    assert later.badge == "fading"


def test_an_untested_item_reads_untested(session) -> None:
    concept = _concept(session)
    item = _item(session, concept)
    assert scheduling.mastery_of(session, item).badge == "untested"


def test_concept_mastery_weights_apply_and_debug_higher(session) -> None:
    """Spec §10.5 — "apply and debug weighted 1.5x"."""
    concept = _concept(session)
    strong = _item(session, concept, dimension="explain")
    weak = _item(session, concept, dimension="apply")

    now = dt.datetime(2026, 8, 22, tzinfo=dt.timezone.utc)
    for _ in range(3):
        scheduling.record_review(session, strong, final_rating=Rating.Easy,
                                 evaluation=_evaluation(5, 5), now=now)
        scheduling.record_review(session, weak, final_rating=Rating.Again,
                                 evaluation=_evaluation(0, 5), now=now)
        now += dt.timedelta(minutes=30)

    result = scheduling.concept_mastery(session, concept.id, now)
    explain = result["dimensions"]["explain"]["mastery"]
    apply_m = result["dimensions"]["apply"]["mastery"]
    unweighted = (explain + apply_m) / 2

    # apply drags the aggregate below a plain mean because it counts 1.5x.
    assert apply_m < explain
    assert result["mastery"] < unweighted


# --------------------------------------------------------------------------
# §10.4 Priority
# --------------------------------------------------------------------------

def test_priority_rises_with_overdueness_lapses_and_importance(session) -> None:
    concept = _concept(session, importance=5.0)
    plain = _concept(session, "Plain", importance=1.0)
    now = dt.datetime(2026, 8, 22, tzinfo=dt.timezone.utc)

    overdue = _item(session, concept, dimension="explain",
                    fsrs_state=str(int(State.Review)), fsrs_stability=2.0,
                    fsrs_difficulty=5.0, due_at=now - dt.timedelta(days=20),
                    reps=3, lapses=4)
    fresh = _item(session, plain, dimension="explain",
                  fsrs_state=str(int(State.Review)), fsrs_stability=2.0,
                  fsrs_difficulty=5.0, due_at=now - dt.timedelta(hours=1),
                  reps=3, lapses=0)

    assert scheduling.priority(session, overdue, now=now) > \
        scheduling.priority(session, fresh, now=now)


def test_a_never_reviewed_item_gets_the_coverage_gap_bonus(session) -> None:
    concept = _concept(session)
    item = _item(session, concept)
    now = dt.datetime(2026, 8, 22, tzinfo=dt.timezone.utc)

    weights = dict(scheduling.DEFAULT_WEIGHTS)
    value = scheduling.priority(session, item, now=now, weights=weights,
                                interview_on=False)
    # forgetting_risk is 1 (never reviewed), importance 1, so the gap shows.
    assert value == pytest.approx(1.0 + weights["w_gap"])


def test_suspended_items_are_never_queued(session) -> None:
    concept = _concept(session)
    _item(session, concept, dimension="explain")
    _item(session, concept, dimension="interview", suspended=True)

    queue = scheduling.build_queue(session, 10)
    assert [i.dimension for i in queue] == ["explain"]


def test_interview_mode_unsuspends_and_resuspends(session) -> None:
    """Spec §10.1 — "A single Settings toggle … Default off.\""""
    concept = _concept(session)
    _item(session, concept, dimension="interview", suspended=True)

    assert scheduling.interview_mode_on(session) is False
    assert scheduling.set_interview_mode(session, True) == 1
    assert scheduling.interview_mode_on(session) is True
    assert [i.dimension for i in scheduling.build_queue(session, 10)] == ["interview"]

    scheduling.set_interview_mode(session, False)
    assert scheduling.build_queue(session, 10) == []


def test_a_merged_away_concept_stops_being_scheduled(session) -> None:
    concept = _concept(session)
    _item(session, concept)
    assert len(scheduling.build_queue(session, 10)) == 1

    concept.deleted_at = dt.datetime.now(dt.timezone.utc)
    concept.status = "archived"
    session.add(concept)
    session.flush()

    assert scheduling.build_queue(session, 10) == []


def test_a_stale_concept_keeps_being_scheduled(session) -> None:
    """Spec §7.4 — "losing the source text does not mean losing the
    knowledge"."""
    concept = _concept(session)
    _item(session, concept, reps=20)
    concept.status = "stale"
    session.add(concept)
    session.flush()

    assert len(scheduling.build_queue(session, 10)) == 1


# --------------------------------------------------------------------------
# The session, end to end
# --------------------------------------------------------------------------

def _run_one(session, answer_text: str | None = None, hits: int | None = None):
    row = revision.create_session(session, count=1)
    item = revision.next_item(session, row.id)
    served = revision.serve(session, item)
    question = session.get(Question, served["question_id"])
    text = answer_text if answer_text is not None else _answer_hitting(
        question, hits if hits is not None else 3
    )
    feedback = revision.answer(session, row.id, item.id, text, response_ms=9000)
    return row, item, question, feedback


def test_a_full_prose_session_runs_and_lands_in_fsrs(session) -> None:
    """Phase 7's done-when."""
    concept = _concept(session)
    item = _item(session, concept)

    row, session_item, question, feedback = _run_one(session, hits=3)

    assert feedback["rating"] == "easy"
    assert feedback["hit_ratio"] == 1.0
    assert feedback["feedback"]
    assert feedback["expected_answer"]

    session.refresh(item)
    assert item.reps == 1
    assert item.due_at is not None
    assert item.fsrs_stability > 0

    log_row = session.exec(select(ReviewLog)).one()
    assert log_row.rating == int(Rating.Easy)
    assert log_row.question_id == question.id
    assert log_row.evaluator_json

    result = revision.finish(session, row.id)
    assert result["finished"] is True
    assert result["answered"] == 1


def test_questions_are_generated_lazily_with_key_points(session) -> None:
    """Spec §9.2 — "When a review item is served, generate its question
    then"."""
    concept = _concept(session)
    _item(session, concept)

    row = revision.create_session(session, count=1)
    assert session.exec(select(Question)).all() == []

    item = revision.next_item(session, row.id)
    revision.serve(session, item)

    question = session.exec(select(Question)).one()
    points = json.loads(question.key_points_json)
    assert 3 <= len(points) <= 6
    assert question.generation_reason == "due"
    assert question.prompt_version == "question_generation_v1"


def test_a_wrong_answer_records_a_misconception(session) -> None:
    concept = _concept(session)
    _item(session, concept)

    _run_one(session, answer_text="this reveals a misconception badly")

    rows = session.exec(select(Misconception)).all()
    assert len(rows) == 1
    assert rows[0].concept_id == concept.id
    assert rows[0].times_seen == 1


def test_skip_logs_again_and_shows_the_answer(session) -> None:
    """Spec §9.2 — "Logs rating = Again, shows the expected answer and key
    points, and moves on. No penalty framing, no confirmation dialog.\""""
    concept = _concept(session)
    item = _item(session, concept)

    row = revision.create_session(session, count=1)
    session_item = revision.next_item(session, row.id)
    revision.serve(session, session_item)

    feedback = revision.skip(session, row.id, session_item.id)

    assert feedback["skipped"] is True
    assert feedback["rating"] == "again"
    assert feedback["expected_answer"]
    assert feedback["key_point_hits"]
    assert all(p["hit"] is False for p in feedback["key_point_hits"])

    session.refresh(item)
    assert item.lapses == 1
    attempt = session.exec(select(QuestionAttempt)).one()
    assert attempt.user_answer is None


def test_a_question_cannot_be_answered_twice(session) -> None:
    concept = _concept(session)
    _item(session, concept)
    row = revision.create_session(session, count=1)
    item = revision.next_item(session, row.id)
    revision.serve(session, item)
    revision.answer(session, row.id, item.id, "something")

    with pytest.raises(ValueError):
        revision.answer(session, row.id, item.id, "again")


# --------------------------------------------------------------------------
# §9.4 Override, end to end
# --------------------------------------------------------------------------

def test_override_replaces_the_rating_without_compounding(session) -> None:
    concept = _concept(session)
    item = _item(session, concept)

    row, session_item, question, feedback = _run_one(
        session, answer_text="nothing at all"
    )
    assert feedback["rating"] == "again"
    session.refresh(item)
    assert item.reps == 1
    assert item.lapses == 1

    attempt = session.exec(select(QuestionAttempt)).one()
    result = revision.override(session, row.id, attempt.id, "got_it")

    assert result["rating"] == "hard"
    session.refresh(item)
    # One review happened, not two — the override replaced it.
    assert item.reps == 1
    assert item.lapses == 0

    session.refresh(attempt)
    assert attempt.evaluator_rating == int(Rating.Again)   # preserved
    assert attempt.user_override_rating == int(Rating.Hard)
    assert attempt.final_rating == int(Rating.Hard)

    # Both the original and the correction are on the log.
    logs = session.exec(select(ReviewLog).order_by(ReviewLog.id)).all()
    assert [row_.rating for row_ in logs] == [int(Rating.Again), int(Rating.Hard)]


def test_override_wrong_forces_again(session) -> None:
    concept = _concept(session)
    item = _item(session, concept)
    row, _, _, feedback = _run_one(session, hits=3)
    assert feedback["rating"] == "easy"

    attempt = session.exec(select(QuestionAttempt)).one()
    result = revision.override(session, row.id, attempt.id, "wrong")

    assert result["rating"] == "again"
    session.refresh(item)
    assert item.lapses == 1


# --------------------------------------------------------------------------
# §9.5 Immediate retest
# --------------------------------------------------------------------------

def test_only_again_and_hard_are_offered_for_retest(session) -> None:
    concept = _concept(session)
    _item(session, concept, dimension="explain")
    _item(session, concept, dimension="apply")

    row = revision.create_session(session, count=2)
    ratings = []
    for index in range(2):
        item = revision.next_item(session, row.id)
        served = revision.serve(session, item)
        question = session.get(Question, served["question_id"])
        text = _answer_hitting(question, 3 if index == 0 else 0)
        ratings.append(revision.answer(session, row.id, item.id, text)["rating"])

    assert ratings[0] == "easy"
    offers = revision.retest_offers(session, row.id)
    assert len(offers) == 1
    assert offers[0]["rating"] in ("again", "hard")


def test_a_rephrased_retest_generates_a_different_question(session) -> None:
    concept = _concept(session)
    _item(session, concept)
    row, _, question, _ = _run_one(session, answer_text="nothing")

    attempt = session.exec(select(QuestionAttempt)).one()
    same = revision.start_retest(session, row.id, attempt.id, "same")
    rephrased = revision.start_retest(session, row.id, attempt.id, "rephrased")

    assert same["question_id"] == question.id
    assert same["question_text"] == question.question_text
    assert rephrased["question_id"] != question.id
    assert rephrased["question_text"] != question.question_text

    fresh = session.get(Question, rephrased["question_id"])
    assert fresh.generation_reason == "retest_rephrased"


def test_a_retest_never_pushes_the_due_date_further_out(session) -> None:
    """Spec §9.5 **[LOCKED]** — "the first attempt is authoritative for FSRS …
    can never upgrade the original rating or push the due date further out"."""
    concept = _concept(session)
    item = _item(session, concept)

    row, _, _, feedback = _run_one(session, answer_text="nothing at all")
    assert feedback["rating"] == "again"
    session.refresh(item)
    due_after_first = item.due_at
    stability_after_first = item.fsrs_stability

    attempt = session.exec(select(QuestionAttempt)).one()
    retest = revision.start_retest(session, row.id, attempt.id, "same")
    question = session.get(Question, retest["question_id"])

    result = revision.answer_retest(
        session, row.id, question.id, attempt.id,
        _answer_hitting(question, 3),
    )

    assert result["is_retest"] is True
    assert result["rating"] == "easy"          # they got it on the retest
    session.refresh(item)
    # ...but the schedule did not reward that.
    assert item.due_at <= due_after_first
    assert item.fsrs_stability == stability_after_first

    retest_log = session.exec(
        select(ReviewLog).where(ReviewLog.is_retest == True)  # noqa: E712
    ).one()
    assert retest_log.rating == int(Rating.Easy)
    retest_attempt = session.exec(
        select(QuestionAttempt).where(QuestionAttempt.is_retest == True)  # noqa: E712
    ).one()
    assert retest_attempt.retest_of_attempt_id == attempt.id


def test_the_two_halves_of_9_5_conflict_and_the_guard_wins(session) -> None:
    """Spec §9.5 asks for two things that cannot both hold.

    "A retest may shorten the relearning step (if the item is in relearning and
    the retest passes, advance the relearning step) but **can never upgrade the
    original rating or push the due date further out**."

    In FSRS, advancing a relearning step *is* a longer interval — with the
    specced single relearning step (`["10m"]`), passing graduates the card back
    to Review and schedules it days away. So "advance the step" and "never push
    the due date further out" are mutually exclusive here.

    The guard wins, because it is the clause the spec gives a reason for:
    "Otherwise the retest teaches FSRS that the user knew something they did
    not." A passing retest therefore leaves the schedule alone. Recorded in
    DECISIONS.md.
    """
    concept = _concept(session)
    now = dt.datetime(2026, 8, 22, 12, 0, tzinfo=dt.timezone.utc)
    item = _item(session, concept)

    scheduling.record_review(session, item, final_rating=Rating.Easy, now=now)
    scheduling.record_review(session, item, final_rating=Rating.Easy,
                             now=now + dt.timedelta(days=5))
    scheduling.record_review(session, item, final_rating=Rating.Again,
                             now=now + dt.timedelta(days=40))

    assert State(int(item.fsrs_state)) is State.Relearning
    before = (item.due_at, item.fsrs_stability, item.fsrs_step)

    advanced = scheduling.apply_retest(session, item, Rating.Good,
                                       now=now + dt.timedelta(days=40))

    assert advanced is False
    assert (item.due_at, item.fsrs_stability, item.fsrs_step) == before


def test_a_retest_on_an_item_not_in_relearning_is_a_no_op(session) -> None:
    concept = _concept(session)
    now = dt.datetime(2026, 8, 22, tzinfo=dt.timezone.utc)
    item = _item(session, concept)
    scheduling.record_review(session, item, final_rating=Rating.Easy, now=now)
    before = (item.due_at, item.fsrs_stability)

    assert scheduling.apply_retest(session, item, Rating.Easy, now=now) is False
    assert (item.due_at, item.fsrs_stability) == before


def test_a_failed_retest_changes_nothing(session) -> None:
    concept = _concept(session)
    item = _item(session, concept)
    scheduling.record_review(session, item, final_rating=Rating.Again)
    before = (item.due_at, item.fsrs_stability, item.fsrs_step)

    assert scheduling.apply_retest(session, item, Rating.Again) is False
    assert (item.due_at, item.fsrs_stability, item.fsrs_step) == before


# --------------------------------------------------------------------------
# §9.6 Anxiety-aware design
# --------------------------------------------------------------------------

def test_the_default_session_size_is_five(session) -> None:
    """"Default revision session size is 5, not 10. Starting is the hard
    part."""
    assert revision.DEFAULT_SESSION_SIZE == 5
    assert revision.SESSION_SIZES == (5, 10, 20)
    assert revision.dashboard(session)["default_size"] == 5


def test_a_session_of_one_is_a_complete_session(session) -> None:
    """"Ending a session early records it as finished, not abandoned, and the
    summary says what was done rather than what was left."""
    concept = _concept(session)
    _item(session, concept, dimension="explain")
    _item(session, concept, dimension="apply")

    row = revision.create_session(session, count=2)
    item = revision.next_item(session, row.id)
    revision.serve(session, item)
    revision.answer(session, row.id, item.id, "an answer")

    result = revision.finish(session, row.id)

    assert result["finished"] is True
    assert result["answered"] == 1
    # Nothing reports what was "left" or "missed".
    assert "abandoned" not in json.dumps(result)
    assert "remaining" not in json.dumps(result)


def test_the_dashboard_reports_counts_without_escalation(session) -> None:
    """§9.6 — "Show the count of due items, but never a red badge, never an
    exclamation mark, never 'overdue!' styling.\""""
    concept = _concept(session)
    now = dt.datetime.now(dt.timezone.utc)
    _item(session, concept, dimension="explain",
          fsrs_state=str(int(State.Review)), fsrs_stability=1.0,
          fsrs_difficulty=5.0, due_at=now - dt.timedelta(days=30), reps=2)
    _item(session, concept, dimension="apply")

    data = revision.dashboard(session)

    assert data["due_count"] == 2
    assert data["overdue_count"] == 1
    assert data["new_count"] == 1
    # No severity, colour or urgency vocabulary crosses the boundary.
    blob = json.dumps(data).lower()
    for word in ("urgent", "severity", "red", "warning", "behind", "overdue!"):
        assert word not in blob
