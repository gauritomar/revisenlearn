"""Usage and cost (§12.6), adaptive coverage (§10.2) and interview mode
(§10.1, §18 Phase 10).
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fsrs import Rating
from sqlmodel import select

from revisenlearn import revision, scheduling, usage
from revisenlearn.llm import set_provider
from revisenlearn.llm.mock import MockProvider
from revisenlearn.models import (
    Concept,
    ConceptEdge,
    LLMRun,
    ReviewItem,
    Setting,
    Subject,
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


def _concept(session, subject, name, topic=None) -> Concept:
    concept = Concept(canonical_name=name, normalised_name=name.lower(),
                      definition=f"{name} definition.", subject_id=subject.id,
                      topic_id=topic.id if topic else None,
                      importance=3.0, difficulty=3.0)
    session.add(concept)
    session.flush()
    return concept


def _run(session, *, task="mcq_generation", concept=None, usd=0.01,
         when=None, tokens=1000) -> LLMRun:
    row = LLMRun(
        task=task, provider="gemini", model="gemini-3.5-flash-lite",
        input_tokens=tokens // 2, output_tokens=tokens // 2,
        estimated_cost_usd=usd, success=True,
        concept_id=concept.id if concept else None,
        created_at=when or dt.datetime.now(dt.timezone.utc),
    )
    session.add(row)
    session.flush()
    return row


def _set(session, key, value) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value_json=json.dumps(value)))
    else:
        row.value_json = json.dumps(value)
        session.add(row)
    session.flush()


# --------------------------------------------------------------------------
# §12.6 Usage
# --------------------------------------------------------------------------

def test_the_summary_is_labelled_as_an_estimate(session) -> None:
    """Spec §12.6 — "Label it 'Estimated — from token counts, not billing
    data' with a link to the Google Cloud console.\""""
    data = usage.summary(session)

    assert data["disclaimer"] == "Estimated — from token counts, not billing data"
    assert "console.cloud.google.com" in data["billing_console_url"]


def test_spend_is_summed_for_the_current_month_only(session) -> None:
    subject = _subject(session)
    concept = _concept(session, subject, "Hybrid search")
    now = dt.datetime.now(dt.timezone.utc)

    _run(session, concept=concept, usd=0.25, when=now)
    _run(session, concept=concept, usd=0.10, when=now)
    # Last month should not count towards this month's cap.
    last_month = (now.replace(day=1) - dt.timedelta(days=5))
    _run(session, concept=concept, usd=99.0, when=last_month)

    data = usage.summary(session)
    assert data["spent_usd"] == pytest.approx(0.35)
    assert data["calls"] == 2


def test_an_unpriced_call_is_counted_not_treated_as_free(session) -> None:
    subject = _subject(session)
    concept = _concept(session, subject, "Hybrid search")
    _run(session, concept=concept, usd=0.10)
    row = _run(session, concept=concept, usd=0.0)
    row.estimated_cost_usd = None
    session.add(row)
    session.flush()

    data = usage.summary(session)
    assert data["unpriced_calls"] == 1
    assert data["spent_usd"] == pytest.approx(0.10)


def test_the_fx_rate_converts_and_is_configurable(session) -> None:
    """Spec §12.6 — "Display in ₹ and $ with a configurable FX rate"."""
    subject = _subject(session)
    concept = _concept(session, subject, "A")
    _run(session, concept=concept, usd=2.0)

    assert usage.summary(session)["spent_gbp"] is None

    _set(session, "fx_rate_usd_to_gbp", 83.5)
    data = usage.summary(session)
    assert data["fx_rate"] == 83.5
    assert data["spent_gbp"] == pytest.approx(167.0)


def test_the_cap_is_soft_and_escalates_in_two_steps(session) -> None:
    """Spec §12.6 — "at 80% … show a banner. At 100% … require one
    confirmation click before each further LLM call. Never hard-block."""
    subject = _subject(session)
    concept = _concept(session, subject, "A")
    _set(session, "monthly_cap_usd", 10.0)

    _run(session, concept=concept, usd=5.0)
    state = usage.cap_state(session)
    assert state["level"] == "ok"
    assert state["requires_confirmation"] is False

    _run(session, concept=concept, usd=3.5)          # 85%
    state = usage.cap_state(session)
    assert state["level"] == "warn"
    assert state["requires_confirmation"] is False

    _run(session, concept=concept, usd=2.0)          # 105%
    state = usage.cap_state(session)
    assert state["level"] == "over"
    assert state["requires_confirmation"] is True


def test_with_no_cap_set_nothing_escalates(session) -> None:
    subject = _subject(session)
    _run(session, concept=_concept(session, subject, "A"), usd=999.0)

    state = usage.cap_state(session)
    assert state["level"] == "none"
    assert state["cap_usd"] is None
    assert state["requires_confirmation"] is False


def test_the_per_concept_table_matches_the_specs_example(session) -> None:
    """Spec §12.6 — "Transformer attention · 47.2k tokens · ₹18.40 across 23
    generations"."""
    subject = _subject(session)
    concept = _concept(session, subject, "Transformer attention")
    _set(session, "fx_rate_usd_to_gbp", 83.5)
    for _ in range(23):
        _run(session, concept=concept, usd=0.01, tokens=2052)

    rows = usage.by_concept(session)
    row = rows[0]

    assert row["concept_name"] == "Transformer attention"
    assert row["generations"] == 23
    assert row["tokens"] == 23 * 2052        # 47.2k
    assert row["usd"] == pytest.approx(0.23)
    assert row["gbp"] == pytest.approx(19.205)


def test_spend_breaks_down_by_task_and_hierarchy(session) -> None:
    subject = _subject(session)
    topic = Topic(subject_id=subject.id, name="Retrieval")
    session.add(topic)
    session.flush()
    concept = _concept(session, subject, "Hybrid search", topic)

    _run(session, task="concept_extraction", concept=concept, usd=0.05)
    _run(session, task="mcq_generation", concept=concept, usd=0.20)

    by_task = usage.summary(session)["by_task"]
    assert by_task[0]["task"] == "mcq_generation"     # most expensive first
    assert by_task[0]["usd"] == pytest.approx(0.20)

    hierarchy = usage.by_hierarchy(session)
    assert hierarchy["by_subject"][0]["subject"] == "GenAI"
    assert hierarchy["by_subject"][0]["usd"] == pytest.approx(0.25)
    assert hierarchy["by_topic"][0]["topic"] == "Retrieval"


def test_the_daily_sparkline_covers_the_month_so_far(session) -> None:
    subject = _subject(session)
    concept = _concept(session, subject, "A")
    today = dt.datetime.now(dt.timezone.utc)
    _run(session, concept=concept, usd=0.10, when=today)

    days = usage.summary(session)["daily"]
    assert len(days) == today.day
    assert days[-1]["date"] == today.date().isoformat()
    assert days[-1]["usd"] == pytest.approx(0.10)


# --------------------------------------------------------------------------
# §10.2 Adaptive coverage
# --------------------------------------------------------------------------

def _profile(**flags) -> str:
    base = {"recall": True, "explain": True, "apply": False, "debug": False,
            "synthesis": False, "interview": False}
    base.update(flags)
    return json.dumps(base)


def test_two_lapses_on_apply_adds_debug(session) -> None:
    """Spec §10.2 — "adds `debug` to any concept whose `apply` dimension has
    lapsed twice"."""
    from revisenlearn.pipeline.coverage import adaptive_pass

    subject = _subject(session)
    concept = _concept(session, subject, "Hybrid search")
    concept.coverage_profile_json = _profile(apply=True)
    session.add(concept)
    session.add(ReviewItem(concept_id=concept.id, dimension="apply", lapses=2,
                           reps=4))
    session.flush()

    result = adaptive_pass(session)

    assert concept.id in result["added_debug"]
    assert json.loads(concept.coverage_profile_json)["debug"] is True
    dims = {i.dimension for i in session.exec(select(ReviewItem)).all()}
    assert "debug" in dims


def test_one_lapse_is_not_enough(session) -> None:
    from revisenlearn.pipeline.coverage import adaptive_pass

    subject = _subject(session)
    concept = _concept(session, subject, "Hybrid search")
    concept.coverage_profile_json = _profile(apply=True)
    session.add(concept)
    session.add(ReviewItem(concept_id=concept.id, dimension="apply", lapses=1))
    session.flush()

    assert adaptive_pass(session)["added_debug"] == []


def test_adaptive_coverage_never_removes_a_dimension(session) -> None:
    """Spec §10.2 — "Removals are never automatic — only the user removes a
    dimension.\""""
    from revisenlearn.pipeline.coverage import adaptive_pass

    subject = _subject(session)
    concept = _concept(session, subject, "Hybrid search")
    concept.coverage_profile_json = _profile(apply=True, debug=True,
                                             synthesis=True, interview=True)
    session.add(concept)
    session.flush()
    before = json.loads(concept.coverage_profile_json)

    adaptive_pass(session)

    after = json.loads(concept.coverage_profile_json)
    for dimension, enabled in before.items():
        if enabled:
            assert after[dimension] is True, f"{dimension} was removed"


def test_a_well_connected_well_mastered_concept_gains_synthesis(session) -> None:
    """Spec §10.2 — "adds `synthesis` to any concept with three or more
    accepted edges whose `explain` and `apply` are both above 80% mastery"."""
    from revisenlearn.pipeline.coverage import adaptive_pass

    subject = _subject(session)
    concept = _concept(session, subject, "Hybrid search")
    concept.coverage_profile_json = _profile(apply=True)
    session.add(concept)

    for name in ("A", "B", "C"):
        other = _concept(session, subject, name)
        session.add(ConceptEdge(source_concept_id=concept.id,
                                target_concept_id=other.id,
                                relation_type="related_to", status="accepted"))
    session.flush()

    now = dt.datetime(2026, 8, 22, tzinfo=dt.timezone.utc)
    for dimension in ("explain", "apply"):
        item = ReviewItem(concept_id=concept.id, dimension=dimension)
        session.add(item)
        session.flush()
        for _ in range(3):
            scheduling.record_review(
                session, item, final_rating=Rating.Easy,
                evaluation=scheduling.Evaluation(
                    key_point_hits=[{"point": "p", "hit": True}],
                    factually_incorrect_claims=[], misconceptions=[],
                    feedback="",
                ),
                now=now,
            )

    result = adaptive_pass(session, now=now)

    assert concept.id in result["added_synthesis"]
    assert json.loads(concept.coverage_profile_json)["synthesis"] is True


def test_a_poorly_connected_concept_does_not_gain_synthesis(session) -> None:
    from revisenlearn.pipeline.coverage import adaptive_pass

    subject = _subject(session)
    concept = _concept(session, subject, "Hybrid search")
    concept.coverage_profile_json = _profile(apply=True)
    session.add(concept)
    other = _concept(session, subject, "Only one")
    session.add(ConceptEdge(source_concept_id=concept.id,
                            target_concept_id=other.id,
                            relation_type="related_to", status="accepted"))
    session.flush()

    assert adaptive_pass(session)["added_synthesis"] == []


# --------------------------------------------------------------------------
# §10.1 and Phase 10 — interview mode
# --------------------------------------------------------------------------

def _interview_setup(session, count=6) -> Subject:
    subject = _subject(session)
    concepts = []
    for i in range(count):
        concept = _concept(session, subject, f"Concept {i}")
        concepts.append(concept)
        session.add(ReviewItem(concept_id=concept.id, dimension="interview",
                               suspended=True))
    # Connect the first four so a mock round has a neighbourhood to walk.
    for a, b in zip(concepts, concepts[1:4]):
        session.add(ConceptEdge(source_concept_id=a.id, target_concept_id=b.id,
                                relation_type="related_to", status="accepted"))
    session.flush()
    return subject


def test_interview_items_are_suspended_until_the_toggle(session) -> None:
    _interview_setup(session, count=3)

    assert scheduling.build_queue(session, 10) == []
    assert scheduling.interview_mode_on(session) is False

    changed = scheduling.set_interview_mode(session, True)
    assert changed == 3
    assert len(scheduling.build_queue(session, 10)) == 3


def test_a_mock_round_needs_interview_mode_on(session) -> None:
    _interview_setup(session)

    with pytest.raises(ValueError, match="Interview mode is off"):
        revision.mock_round(session)


def test_a_mock_round_serves_five_related_concepts(session) -> None:
    """Spec §18 Phase 10 — "a 'mock round' session type that serves 5 interview
    questions across related concepts"."""
    _interview_setup(session, count=8)
    scheduling.set_interview_mode(session, True)

    row = revision.mock_round(session)

    assert row.planned_count == 5
    assert row.session_type == "revision"
    scope = json.loads(row.scope_json)
    assert scope["mock_round"] is True
    assert scope["seed_concept_id"]

    items = session.exec(
        select(revision.SessionItem).where(
            revision.SessionItem.session_id == row.id)
    ).all()
    assert len(items) == 5
    # Every one is an interview item.
    for item in items:
        review_item = session.get(ReviewItem, item.review_item_id)
        assert review_item.dimension == "interview"


def test_a_mock_round_fills_even_with_a_thin_neighbourhood(session) -> None:
    """A short neighbourhood must still give a full round rather than a
    two-question one."""
    _interview_setup(session, count=6)
    # Drop every edge, so nothing is "related".
    for edge in session.exec(select(ConceptEdge)).all():
        session.delete(edge)
    session.flush()
    scheduling.set_interview_mode(session, True)

    row = revision.mock_round(session)
    assert row.planned_count == 5


def test_interview_questions_use_the_interview_prompt(session) -> None:
    """Spec §18 Phase 10 — "interview-specific prompt tuning". §11 forbids
    editing a prompt in place, so this is a separate version."""
    from revisenlearn.models import Question

    _interview_setup(session, count=3)
    scheduling.set_interview_mode(session, True)
    row = revision.mock_round(session, count=1)

    item = revision.next_item(session, row.id)
    revision.serve(session, item)

    question = session.exec(select(Question)).one()
    assert question.prompt_version == "question_generation_v2_interview"
    assert question.dimension == "interview"

    # And it is logged under that version too (§1.6).
    run = session.exec(
        select(LLMRun).where(LLMRun.task == "question_generation")
    ).one()
    assert run.prompt_version == "question_generation_v2_interview"


def test_a_non_interview_question_still_uses_v1(session) -> None:
    from revisenlearn.models import Question

    subject = _subject(session)
    concept = _concept(session, subject, "Hybrid search")
    session.add(ReviewItem(concept_id=concept.id, dimension="explain"))
    session.flush()

    row = revision.create_session(session, count=1)
    item = revision.next_item(session, row.id)
    revision.serve(session, item)

    assert session.exec(select(Question)).one().prompt_version == \
        "question_generation_v1"


def test_turning_interview_mode_off_resuspends(session) -> None:
    _interview_setup(session, count=3)
    scheduling.set_interview_mode(session, True)
    assert len(scheduling.build_queue(session, 10)) == 3

    scheduling.set_interview_mode(session, False)

    assert scheduling.build_queue(session, 10) == []
    assert all(i.suspended for i in session.exec(select(ReviewItem)).all())
