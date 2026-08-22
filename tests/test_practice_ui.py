"""Quick Practice in a real browser (spec §9.1).

Phase 6 is *done when* "the user can do a 50-MCQ session end to end" (§18),
so that is exactly what the last test here does — fifty questions, clicked.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from conftest import start_app

pytestmark = pytest.mark.ui


@pytest.fixture
def practice_app(db_path: Path):
    instance = start_app(db_path, extra_env={"RNL_LLM_PROVIDER": "mock"})
    try:
        yield instance
    finally:
        instance.stop()


def seed_mcqs(app, concepts: int = 6, per_concept: int = 10) -> None:
    """Insert a pool directly. Generation is covered in test_practice.py; this
    file is about the runner."""
    conn = sqlite3.connect(app.db_path)
    conn.execute(
        "INSERT INTO subjects (name, sort_order, created_at) "
        "VALUES ('GenAI', 0, '2026-08-22')"
    )
    subject_id = conn.execute("SELECT id FROM subjects").fetchone()[0]

    options = json.dumps([
        {"id": "a", "text": "The correct account"},
        {"id": "b", "text": "A plausible confusion"},
        {"id": "c", "text": "An adjacent idea"},
        {"id": "d", "text": "A boundary-case error"},
    ])
    for c in range(concepts):
        conn.execute(
            "INSERT INTO concepts (canonical_name, normalised_name, definition, "
            "subject_id, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'active', '2026-08-22', '2026-08-22')",
            (f"Concept {c}", f"concept {c}", f"Definition {c}.", subject_id),
        )
        concept_id = conn.execute(
            "SELECT id FROM concepts ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        for q in range(per_concept):
            conn.execute(
                "INSERT INTO mcqs (concept_id, dimension, stem, options_json, "
                "correct_option_id, explanation, status, times_served, "
                "times_correct, consecutive_correct, created_at) "
                "VALUES (?, 'recall', ?, ?, 'a', ?, 'active', 0, 0, 0, "
                "'2026-08-22')",
                (concept_id, f"C{c} Q{q}: which statement holds?", options,
                 f"Option a is right for concept {c}."),
            )
    conn.commit()
    conn.close()


@pytest.fixture
def page_with_pool(browser, practice_app):
    seed_mcqs(practice_app)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    p = context.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(practice_app.base_url, wait_until="networkidle")
    p.get_by_test_id("nav-practice").click()
    p.get_by_test_id("practice-picker").wait_for(state="visible")
    try:
        yield p
    finally:
        assert not errors, f"Uncaught JavaScript errors: {errors}"
        context.close()


def test_practice_is_reachable_and_reports_the_pool(page_with_pool) -> None:
    available = page_with_pool.get_by_test_id("practice-available")
    assert "60 active questions" in available.inner_text()
    assert "6 concepts" in available.inner_text()


def test_with_no_questions_practice_says_so(browser, practice_app) -> None:
    """Honest empty state rather than an error."""
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.goto(practice_app.base_url, wait_until="networkidle")
        page.get_by_test_id("nav-practice").click()
        empty = page.get_by_test_id("practice-empty")
        empty.wait_for(state="visible")
        assert "Process notes" in empty.inner_text()
    finally:
        context.close()


def test_answering_gives_instant_feedback(page_with_pool, practice_app) -> None:
    page = page_with_pool
    page.get_by_test_id("count-20").click()
    page.get_by_test_id("start-practice").click()
    page.get_by_test_id("practice-runner").wait_for(state="visible")

    assert page.get_by_test_id("practice-stem").inner_text()
    assert page.get_by_test_id("practice-stopwatch").is_visible()

    page.get_by_test_id("option-b").click()

    feedback = page.get_by_test_id("practice-feedback")
    feedback.wait_for(state="visible")
    assert feedback.get_attribute("data-correct") == "false"
    assert "Option a is right" in feedback.inner_text()
    # The correct option is marked even though the user picked another.
    assert page.get_by_test_id("option-a").get_attribute("data-correct") == "true"

    assert practice_app.query(
        "SELECT is_correct FROM mcq_attempts"
    ) == [(0,)]


def test_number_keys_answer_and_space_advances(page_with_pool) -> None:
    """Spec §14.4 — `1`–`4` select an option, `Space` next question."""
    page = page_with_pool
    page.get_by_test_id("start-practice").click()
    page.get_by_test_id("practice-runner").wait_for(state="visible")
    first = page.get_by_test_id("practice-stem").inner_text()

    page.keyboard.press("1")
    page.get_by_test_id("practice-feedback").wait_for(state="visible")

    page.keyboard.press(" ")
    page.wait_for_function(
        f"() => document.querySelector('[data-testid=practice-stem]')"
        f".textContent !== {json.dumps(first)}",
        timeout=10_000,
    )
    assert page.get_by_test_id("practice-feedback").count() == 0


def test_option_order_is_shuffled_between_questions(page_with_pool) -> None:
    """Spec §9.1 — "shuffle option order every serve"."""
    page = page_with_pool
    page.get_by_test_id("start-practice").click()
    page.get_by_test_id("practice-runner").wait_for(state="visible")

    orders = set()
    for _ in range(10):
        texts = page.locator("[data-testid^='option-']").all_inner_texts()
        orders.add(tuple(t.strip() for t in texts))
        page.keyboard.press("1")
        page.get_by_test_id("practice-feedback").wait_for(state="visible")
        page.keyboard.press(" ")
        page.wait_for_timeout(120)

    assert len(orders) > 1, "option order never changed across serves"


def test_mcq_answers_never_touch_scheduling(page_with_pool, practice_app) -> None:
    """Spec §9.1 [LOCKED] — practice feeds statistics only. Recognition is not
    recall."""
    page = page_with_pool
    page.get_by_test_id("start-practice").click()
    page.get_by_test_id("practice-runner").wait_for(state="visible")

    for _ in range(3):
        page.keyboard.press("1")
        page.get_by_test_id("practice-feedback").wait_for(state="visible")
        page.keyboard.press(" ")
        page.wait_for_timeout(120)

    assert practice_app.query("SELECT count(*) FROM mcq_attempts")[0][0] == 3
    # Nothing was scheduled, and the append-only log stayed empty.
    assert practice_app.query("SELECT count(*) FROM review_logs")[0][0] == 0
    assert practice_app.query("SELECT count(*) FROM review_items")[0][0] == 0


def test_a_fifty_question_session_end_to_end(page_with_pool, practice_app) -> None:
    """Phase 6's done-when, clicked through in the browser."""
    page = page_with_pool
    page.get_by_test_id("count-50").click()
    page.get_by_test_id("start-practice").click()
    page.get_by_test_id("practice-runner").wait_for(state="visible")

    for index in range(50):
        page.get_by_test_id("practice-stem").wait_for(state="visible")
        # Alternate right and wrong so the summary has something to say.
        page.keyboard.press("1" if index % 2 == 0 else "2")
        page.get_by_test_id("practice-feedback").wait_for(state="visible",
                                                          timeout=15_000)
        if index < 49:
            page.keyboard.press(" ")
            page.wait_for_timeout(80)

    # The last Space runs off the end and lands on the summary.
    page.keyboard.press(" ")
    summary = page.get_by_test_id("practice-summary")
    summary.wait_for(state="visible", timeout=20_000)

    text = summary.inner_text()
    assert "Session complete" in text
    assert "/50" in text

    # The database agrees.
    assert practice_app.query("SELECT count(*) FROM mcq_attempts")[0][0] == 50
    completed, correct, finished = practice_app.query(
        "SELECT completed_count, correct_count, finished_at IS NOT NULL "
        "FROM sessions"
    )[0]
    assert completed == 50
    assert finished == 1
    assert correct > 0

    # Per-concept breakdown is there (§9.1 summary).
    assert page.get_by_test_id("summary-concepts").locator("li").count() >= 1


def test_practice_does_not_scroll_sideways_when_narrow(page_with_pool) -> None:
    page = page_with_pool
    page.get_by_test_id("start-practice").click()
    page.get_by_test_id("practice-runner").wait_for(state="visible")
    page.set_viewport_size({"width": 500, "height": 900})
    page.wait_for_timeout(250)

    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"page scrolls horizontally by {overflow}px at 500px"
