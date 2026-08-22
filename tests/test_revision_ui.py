"""The prose revision loop in a real browser (spec §9.2–§9.6).

§9.6 is a design contract, not decoration, so several of these tests assert its
absences: no red badge on the due count, no penalty framing on skip, no
"abandoned" language when a session ends early.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from conftest import start_app

pytestmark = pytest.mark.ui


@pytest.fixture
def revision_app(db_path: Path):
    instance = start_app(db_path, extra_env={"RNL_LLM_PROVIDER": "mock"})
    try:
        yield instance
    finally:
        instance.stop()


def seed_review_items(app, concepts: int = 3) -> None:
    """Concepts with review items that have never been reviewed, so they are
    immediately eligible."""
    conn = sqlite3.connect(app.db_path)
    conn.execute(
        "INSERT INTO subjects (name, sort_order, created_at) "
        "VALUES ('GenAI', 0, '2026-08-22')"
    )
    subject_id = conn.execute("SELECT id FROM subjects").fetchone()[0]
    for c in range(concepts):
        conn.execute(
            "INSERT INTO concepts (canonical_name, normalised_name, definition, "
            "subject_id, importance, difficulty, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 3.0, 3.0, 'active', '2026-08-22', '2026-08-22')",
            (f"Concept {c}", f"concept {c}", f"Definition of concept {c}.",
             subject_id),
        )
        concept_id = conn.execute(
            "SELECT id FROM concepts ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO review_items (concept_id, dimension, lapses, reps, "
            "suspended, created_at, updated_at) "
            "VALUES (?, 'explain', 0, 0, 0, '2026-08-22', '2026-08-22')",
            (concept_id,),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def page_with_due(browser, revision_app):
    seed_review_items(revision_app)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    p = context.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(revision_app.base_url, wait_until="networkidle")
    p.get_by_test_id("nav-revision").click()
    p.get_by_test_id("revision-dashboard").wait_for(state="visible")
    try:
        yield p
    finally:
        assert not errors, f"Uncaught JavaScript errors: {errors}"
        context.close()


def _start(page, count_testid="revision-count-5"):
    page.get_by_test_id(count_testid).click()
    page.get_by_test_id("start-revision").click()
    page.get_by_test_id("revision-runner").wait_for(state="visible", timeout=20_000)


def test_the_due_count_is_neutral(page_with_due) -> None:
    """Spec §9.6 — "never a red badge, never an exclamation mark, never
    'overdue!' styling. A neutral grey count.\""""
    due = page_with_due.get_by_test_id("revision-due")
    due.wait_for(state="visible")
    # The panel renders a 0 before the count arrives, so wait for the fetch
    # rather than reading whichever frame is on screen.
    page_with_due.wait_for_function(
        "() => document.querySelector('[data-testid=revision-due]')"
        "?.innerText.includes('3')",
        timeout=10_000,
    )

    body = page_with_due.get_by_test_id("revision-dashboard").inner_text()
    assert "!" not in body
    for word in ["overdue", "behind", "urgent", "must", "should have"]:
        assert word not in body.lower()

    # And nothing is painted in a warning colour.
    colour = due.evaluate(
        "el => getComputedStyle(el.querySelector('div')).color"
    )
    assert colour not in ("rgb(245, 158, 11)", "rgb(255, 0, 0)")


def test_the_default_session_size_is_five(page_with_due) -> None:
    """§9.6 — "make the smallest unit genuinely small"."""
    button = page_with_due.get_by_test_id("revision-count-5")
    assert "font-medium" in (button.get_attribute("class") or "")
    assert "Review 5" in page_with_due.get_by_test_id("start-revision").inner_text()


def test_answering_shows_key_points_and_a_rating(page_with_due, revision_app) -> None:
    page = page_with_due
    _start(page)

    assert page.get_by_test_id("revision-question").inner_text()
    assert page.get_by_test_id("revision-stopwatch").is_visible()

    # The mock evaluator hits a key point when its first three words appear.
    page.get_by_test_id("revision-answer").fill(
        "States what Hybrid describes. Explains why Hybrid matters here."
    )
    page.get_by_test_id("revision-submit").click()

    feedback = page.get_by_test_id("revision-feedback")
    feedback.wait_for(state="visible", timeout=20_000)
    assert page.get_by_test_id("key-points").locator("li").count() >= 3
    assert page.get_by_test_id("revision-rating").inner_text()

    # It landed in the append-only log and moved FSRS.
    assert revision_app.query("SELECT count(*) FROM review_logs")[0][0] == 1
    due_at, reps = revision_app.query(
        "SELECT due_at IS NOT NULL, reps FROM review_items WHERE reps > 0"
    )[0]
    assert due_at == 1
    assert reps == 1


def test_the_skip_button_is_as_prominent_as_submit(page_with_due) -> None:
    """Spec §9.6 — "The skip button is as visually prominent as the submit
    button. Skipping is a legitimate move, not a failure.\""""
    page = page_with_due
    _start(page)

    submit = page.get_by_test_id("revision-submit").bounding_box()
    skip = page.get_by_test_id("revision-skip").bounding_box()

    assert skip["height"] == pytest.approx(submit["height"], abs=2)
    assert skip["width"] >= submit["width"] * 0.6
    # Same row, so neither is tucked away.
    assert abs(skip["y"] - submit["y"]) < 4

    text = page.get_by_test_id("revision-skip").inner_text()
    assert "I don" in text
    # No penalty framing.
    assert "fail" not in text.lower()
    assert "give up" not in text.lower()


def test_skipping_logs_again_and_shows_the_answer(page_with_due, revision_app) -> None:
    page = page_with_due
    _start(page)
    page.get_by_test_id("revision-skip").click()

    feedback = page.get_by_test_id("revision-feedback")
    feedback.wait_for(state="visible", timeout=20_000)
    assert feedback.get_attribute("data-rating") == "again"
    # No confirmation dialog appeared.
    assert page.get_by_test_id("revision-answer").count() == 0

    assert revision_app.query(
        "SELECT rating FROM review_logs"
    )[0][0] == 1   # Rating.Again


def test_both_override_buttons_are_always_present(page_with_due, revision_app) -> None:
    """Spec §9.4 — "After every evaluation, two buttons are always present"."""
    page = page_with_due
    _start(page)
    page.get_by_test_id("revision-answer").fill("nothing much at all")
    page.get_by_test_id("revision-submit").click()
    page.get_by_test_id("revision-feedback").wait_for(state="visible", timeout=20_000)

    assert page.get_by_test_id("override-got-it").is_visible()
    assert page.get_by_test_id("override-wrong").is_visible()

    page.get_by_test_id("override-got-it").click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=revision-rating]')"
        "?.textContent.trim() !== 'again'",
        timeout=15_000,
    )

    # Both the evaluator's verdict and the correction are on the log.
    ratings = [r[0] for r in revision_app.query(
        "SELECT rating FROM review_logs ORDER BY id"
    )]
    assert ratings == [1, 2]        # Again, then Hard
    overrides = revision_app.query(
        "SELECT evaluator_rating, user_override_rating, final_rating "
        "FROM question_attempts"
    )[0]
    assert overrides == (1, 2, 2)


def test_a_session_of_one_is_complete(page_with_due, revision_app) -> None:
    """Spec §9.6 — "Ending a session early records it as finished, not
    abandoned, and the summary says what was done rather than what was left.\""""
    page = page_with_due
    _start(page)
    page.get_by_test_id("revision-answer").fill("a first answer")
    page.get_by_test_id("revision-submit").click()
    page.get_by_test_id("revision-feedback").wait_for(state="visible", timeout=20_000)

    # Leave via the header rather than working through all five.
    page.get_by_test_id("nav-dashboard").click()
    page.get_by_test_id("dashboard").wait_for(state="visible")

    completed = revision_app.query(
        "SELECT completed_count FROM sessions WHERE session_type = 'revision'"
    )[0][0]
    assert completed == 1


def test_the_summary_says_what_was_done(page_with_due) -> None:
    page = page_with_due
    page.get_by_test_id("revision-count-5").click()
    # One item only, so the session ends after a single answer.
    page.get_by_test_id("revision-count-custom").fill("1")
    page.get_by_test_id("start-revision").click()
    page.get_by_test_id("revision-runner").wait_for(state="visible", timeout=20_000)

    page.get_by_test_id("revision-answer").fill("an answer")
    page.get_by_test_id("revision-submit").click()
    page.get_by_test_id("revision-feedback").wait_for(state="visible", timeout=20_000)
    page.get_by_test_id("revision-next").click()

    summary = page.get_by_test_id("revision-summary")
    summary.wait_for(state="visible", timeout=20_000)
    text = summary.inner_text()

    assert "1 answered" in text
    assert "That counts." in text
    for word in ["abandoned", "incomplete", "left", "remaining", "missed"]:
        assert word not in text.lower()


def test_a_failed_answer_is_offered_a_retest(page_with_due, revision_app) -> None:
    """Spec §9.5 — retests are offered for Again or Hard."""
    page = page_with_due
    page.get_by_test_id("revision-count-custom").fill("1")
    page.get_by_test_id("start-revision").click()
    page.get_by_test_id("revision-runner").wait_for(state="visible", timeout=20_000)

    page.get_by_test_id("revision-answer").fill("nothing relevant whatsoever")
    page.get_by_test_id("revision-submit").click()
    page.get_by_test_id("revision-feedback").wait_for(state="visible", timeout=20_000)
    page.get_by_test_id("revision-next").click()

    offers = page.get_by_test_id("retest-offers")
    offers.wait_for(state="visible", timeout=20_000)
    assert "cannot make your schedule worse" in offers.inner_text()

    attempt_id = revision_app.query(
        "SELECT id FROM question_attempts ORDER BY id LIMIT 1"
    )[0][0]
    page.get_by_test_id(f"retest-rephrased-{attempt_id}").click()

    runner = page.get_by_test_id("retest-runner")
    runner.wait_for(state="visible", timeout=20_000)
    page.get_by_test_id("retest-answer").fill(
        "States what Concept describes. Explains why Concept matters. "
        "Names a condition under which it fails."
    )
    page.get_by_test_id("retest-submit").click()
    page.get_by_test_id("retest-feedback").wait_for(state="visible", timeout=20_000)

    # Logged as a retest, and the first answer still governs the schedule.
    retests = revision_app.query(
        "SELECT is_retest, retest_of_attempt_id FROM question_attempts "
        "WHERE is_retest = 1"
    )
    assert retests == [(1, attempt_id)]
    assert revision_app.query(
        "SELECT count(*) FROM review_logs WHERE is_retest = 1"
    )[0][0] == 1


def test_revision_does_not_scroll_sideways_when_narrow(page_with_due) -> None:
    page = page_with_due
    _start(page)
    page.set_viewport_size({"width": 500, "height": 900})
    page.wait_for_timeout(250)
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"page scrolls horizontally by {overflow}px at 500px"


def test_practice_is_never_gated_behind_revision(page_with_due) -> None:
    """Spec §9.6 — "Never gate Quick Practice behind Revision. No nags, no
    'you haven't done your revision' modals, no locked buttons.\""""
    page = page_with_due
    assert page.get_by_test_id("nav-practice").is_enabled()
    page.get_by_test_id("nav-practice").click()
    # It opens directly; nothing intercepts.
    page.get_by_test_id("practice-picker").wait_for(state="visible")
    body = page.get_by_test_id("practice-picker").inner_text().lower()
    assert "revision" not in body
