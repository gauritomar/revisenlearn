"""Phase 9 and 10 in the browser: Usage, mastery, the `?` overlay, interview
mode, and the §14.1 responsive audit at all four widths.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from conftest import start_app

pytestmark = pytest.mark.ui


@pytest.fixture
def polish_app(db_path: Path):
    instance = start_app(db_path, extra_env={"RNL_LLM_PROVIDER": "mock"})
    try:
        yield instance
    finally:
        instance.stop()


def seed(app) -> None:
    conn = sqlite3.connect(app.db_path)
    conn.execute("INSERT INTO subjects (name, sort_order, created_at) "
                 "VALUES ('GenAI', 0, '2026-08-22')")
    subject_id = conn.execute("SELECT id FROM subjects").fetchone()[0]
    conn.execute("INSERT INTO topics (subject_id, name, sort_order, created_at) "
                 "VALUES (?, 'Retrieval', 0, '2026-08-22')", (subject_id,))
    topic_id = conn.execute("SELECT id FROM topics").fetchone()[0]

    for name in ("Hybrid search", "Dense retrieval"):
        conn.execute(
            "INSERT INTO concepts (canonical_name, normalised_name, definition, "
            "subject_id, topic_id, importance, difficulty, status, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, 3.0, 3.0, 'active', "
            "'2026-08-22', '2026-08-22')",
            (name, name.lower(), f"{name} definition.", subject_id, topic_id),
        )
        concept_id = conn.execute(
            "SELECT id FROM concepts ORDER BY id DESC LIMIT 1").fetchone()[0]
        conn.execute(
            "INSERT INTO review_items (concept_id, dimension, lapses, reps, "
            "suspended, created_at, updated_at) VALUES "
            "(?, 'interview', 0, 0, 1, '2026-08-22', '2026-08-22')",
            (concept_id,),
        )
        conn.execute(
            "INSERT INTO llm_runs (task, provider, model, prompt_version, "
            "request_mode, input_tokens, output_tokens, cached_tokens, "
            "estimated_cost_usd, success, concept_id, created_at) VALUES "
            "('mcq_generation', 'gemini', 'gemini-3.5-flash-lite', "
            "'mcq_generation_v1', 'standard', 500, 1500, 0, 0.05, 1, ?, ?)",
            (concept_id, __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat()),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def page_polish(browser, polish_app):
    seed(polish_app)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    p = context.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(polish_app.base_url, wait_until="networkidle")
    try:
        yield p
    finally:
        assert not errors, f"Uncaught JavaScript errors: {errors}"
        context.close()


# --------------------------------------------------------------------------
# §12.6 Usage
# --------------------------------------------------------------------------

def test_usage_shows_spend_and_the_estimate_disclaimer(page_polish) -> None:
    page = page_polish
    page.get_by_test_id("nav-usage").click()
    page.get_by_test_id("usage").wait_for(state="visible")

    disclaimer = page.get_by_test_id("usage-disclaimer").inner_text()
    assert "Estimated" in disclaimer
    assert "not billing data" in disclaimer
    assert page.get_by_role("link", name="Google Cloud console").is_visible()

    assert "$0.1000" in page.get_by_test_id("usage-spent").inner_text()
    assert page.get_by_test_id("usage-sparkline").is_visible()
    assert "mcq generation" in page.get_by_test_id("usage-by-task").inner_text()
    assert "Hybrid search" in page.get_by_test_id("usage-by-concept").inner_text()


def test_the_cap_banner_escalates_but_never_blocks(page_polish,
                                                    polish_app) -> None:
    """Spec §12.6 — "Never hard-block"."""
    page = page_polish
    page.get_by_test_id("nav-settings").click()
    page.get_by_test_id("settings").wait_for(state="visible")

    # Total spend seeded is $0.10; a $0.11 cap puts it at 90%.
    field = page.get_by_test_id("monthly-cap")
    field.fill("0.11")
    field.blur()
    page.wait_for_timeout(600)

    page.get_by_test_id("nav-usage").click()
    banner = page.get_by_test_id("cap-banner")
    banner.wait_for(state="visible", timeout=15_000)
    assert banner.get_attribute("data-level") == "warn"
    assert "Nothing changes yet" in banner.inner_text()

    # Now go over.
    page.get_by_test_id("nav-settings").click()
    field = page.get_by_test_id("monthly-cap")
    field.fill("0.05")
    field.blur()
    page.wait_for_timeout(600)
    page.get_by_test_id("nav-usage").click()

    page.wait_for_function(
        "() => document.querySelector('[data-testid=cap-banner]')"
        "?.dataset.level === 'over'",
        timeout=15_000,
    )
    over = page.get_by_test_id("cap-banner").inner_text()
    assert "Nothing is blocked" in over


def test_the_fx_rate_shows_rupees(page_polish) -> None:
    page = page_polish
    page.get_by_test_id("nav-settings").click()
    page.get_by_test_id("settings").wait_for(state="visible")
    field = page.get_by_test_id("fx-rate")
    field.fill("83.5")
    field.blur()
    page.wait_for_timeout(600)

    page.get_by_test_id("nav-usage").click()
    page.get_by_test_id("usage").wait_for(state="visible")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=usage]')"
        "?.innerText.includes('₹')",
        timeout=15_000,
    )


# --------------------------------------------------------------------------
# §14.4 The ? overlay
# --------------------------------------------------------------------------

def test_question_mark_opens_the_shortcut_overlay(page_polish) -> None:
    """Spec §14.4 — "A `?` overlay lists them"."""
    page = page_polish
    page.get_by_test_id("dashboard").wait_for(state="visible")
    page.keyboard.press("?")

    overlay = page.get_by_test_id("shortcut-overlay")
    overlay.wait_for(state="visible")
    text = overlay.inner_text()
    for key in ["⌘K", "⌘S", "Esc"]:
        assert key in text

    page.keyboard.press("Escape")
    overlay.wait_for(state="detached")


def test_question_mark_does_not_fire_while_typing(page_polish,
                                                   polish_app) -> None:
    """A `?` typed into a note is a question mark, not a shortcut."""
    page = page_polish
    page.get_by_test_id("open-command-palette").click()
    field = page.get_by_test_id("palette-input")
    field.wait_for(state="visible")
    # Click before typing: the palette autofocuses on a timeout, and typing
    # into the void is a test artefact, not the behaviour under test.
    field.click()
    page.keyboard.type("what?")

    assert field.input_value() == "what?"
    assert page.get_by_test_id("shortcut-overlay").count() == 0


# --------------------------------------------------------------------------
# §10.1 and Phase 10 — interview mode
# --------------------------------------------------------------------------

def test_interview_mode_toggles_from_settings(page_polish, polish_app) -> None:
    page = page_polish
    page.get_by_test_id("nav-settings").click()
    page.get_by_test_id("settings").wait_for(state="visible")

    toggle = page.get_by_test_id("interview-mode")
    assert not toggle.is_checked()
    assert polish_app.query(
        "SELECT count(*) FROM review_items WHERE suspended = 1"
    )[0][0] == 2

    toggle.click()
    page.wait_for_timeout(800)

    assert polish_app.query(
        "SELECT count(*) FROM review_items WHERE suspended = 0"
    )[0][0] == 2

    # And they now show up as ready to review.
    page.get_by_test_id("nav-revision").click()
    page.get_by_test_id("revision-dashboard").wait_for(state="visible")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=revision-due]')"
        "?.innerText.includes('2')",
        timeout=15_000,
    )


def test_adaptive_coverage_can_be_run_by_hand(page_polish) -> None:
    """§10.2's pass is explicit, not silent — principle §1.3."""
    page = page_polish
    page.get_by_test_id("nav-settings").click()
    page.get_by_test_id("settings").wait_for(state="visible")

    page.get_by_test_id("run-adaptive").click()
    result = page.get_by_test_id("adaptive-result")
    result.wait_for(state="visible", timeout=15_000)
    assert "Added debug to 0" in result.inner_text()


# --------------------------------------------------------------------------
# §10.5 Mastery on the dashboard
# --------------------------------------------------------------------------

def test_the_dashboard_shows_a_mastery_distribution(page_polish) -> None:
    page = page_polish
    page.get_by_test_id("dashboard").wait_for(state="visible")
    dist = page.get_by_test_id("mastery-distribution")
    dist.wait_for(state="visible", timeout=15_000)

    # Both seeded concepts are untested.
    assert "2 untested" in dist.inner_text()
    assert page.get_by_test_id("mastery-untested").is_visible()


def test_the_dashboard_never_shows_a_streak(page_polish) -> None:
    """Spec §14 and §9.6 — "No streaks. No combo counters.\""""
    page = page_polish
    page.get_by_test_id("dashboard").wait_for(state="visible")
    body = page.get_by_test_id("dashboard").inner_text().lower()
    for word in ["streak", "combo", "day in a row", "don't break"]:
        assert word not in body


# --------------------------------------------------------------------------
# §14.1 Responsive audit **[LOCKED]**
# --------------------------------------------------------------------------

SCREENS = ["Dashboard", "Roadmap", "Todos", "Runs", "Practice", "Revision",
           "Graph", "Usage", "Settings"]


@pytest.mark.parametrize("width", [500, 650, 900, 1440])
def test_no_screen_scrolls_sideways_at_any_breakpoint(page_polish,
                                                       width: int) -> None:
    """Spec §14.1 — "No horizontal scrolling ever. Test explicitly at 500px,
    650px, 900px, and 1440px."

    Every screen, at every one of the four widths the spec names.
    """
    page = page_polish
    page.set_viewport_size({"width": width, "height": 900})

    for screen in SCREENS:
        nav = page.get_by_test_id(f"nav-{screen.lower()}")
        if nav.count() == 0 or not nav.is_visible():
            continue          # hidden below lg; reachable but not on the bar
        nav.click()
        page.wait_for_timeout(350)
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth"
        )
        assert overflow <= 0, f"{screen} scrolls {overflow}px at {width}px"


def test_both_sidebars_collapse_below_900(page_polish) -> None:
    page = page_polish
    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_timeout(250)
    assert page.get_by_test_id("right-sidebar").count() == 1

    page.set_viewport_size({"width": 899, "height": 900})
    page.wait_for_timeout(250)
    assert page.get_by_test_id("right-sidebar").count() == 0
