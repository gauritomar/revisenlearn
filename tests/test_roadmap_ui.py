"""Roadmap and Todos in a real browser (addendum §5, §6, §7).

§5 and §7 are `[LOCKED]`, so both are asserted directly: the progress bars must
carry no mastery vocabulary or traffic-light colour, and the tree builder must
be the whole authoring flow — Enter to add, with no dialog anywhere.

The consolidated addendum §2 changed what "an item" is: checklist items are
note blocks now, so the builder's old Tab-into-item-mode is gone. Tab opens
the new lesson's note instead, which is where items are written.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest

from conftest import start_app

pytestmark = pytest.mark.ui


@pytest.fixture
def roadmap_app(db_path: Path):
    instance = start_app(db_path, extra_env={"RNL_LLM_PROVIDER": "mock"})
    try:
        yield instance
    finally:
        instance.stop()


def seed_tree(app) -> None:
    conn = sqlite3.connect(app.db_path)
    conn.execute(
        "INSERT INTO subjects (name, colour, sort_order, created_at) "
        "VALUES ('GenAI', '#6366F1', 0, '2026-08-22')"
    )
    subject_id = conn.execute("SELECT id FROM subjects").fetchone()[0]
    conn.execute(
        "INSERT INTO topics (subject_id, name, sort_order, created_at) "
        "VALUES (?, 'Retrieval', 0, '2026-08-22')", (subject_id,)
    )
    topic_id = conn.execute("SELECT id FROM topics").fetchone()[0]
    conn.execute(
        "INSERT INTO subtopics (topic_id, name, sort_order, created_at) "
        "VALUES (?, 'Hybrid search', 0, '2026-08-22')", (topic_id,)
    )
    conn.commit()
    conn.close()


@pytest.fixture
def page_roadmap(browser, roadmap_app):
    seed_tree(roadmap_app)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    p = context.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(roadmap_app.base_url, wait_until="networkidle")
    p.get_by_test_id("nav-roadmap").click()
    p.get_by_test_id("roadmap").wait_for(state="visible")
    try:
        yield p
    finally:
        assert not errors, f"Uncaught JavaScript errors: {errors}"
        context.close()


def _subtopic_id(app) -> int:
    return app.query("SELECT id FROM subtopics")[0][0]


def _lesson_field(page, app):
    """Open the subtopic's "+ Lesson" field and return it.

    Adding is one click deeper than it was: the Roadmap is now the only place
    that adds *and* deletes, so every row keeps its controls tucked away until
    it is hovered rather than showing a permanent input per subtopic.
    """
    sid = _subtopic_id(app)
    page.get_by_test_id(f"roadmap-open-subtopic-{sid}").hover()
    page.get_by_test_id(f"add-subtopic-child-{sid}").click()
    field = page.get_by_test_id(f"add-lesson-subtopic-{sid}")
    field.wait_for(state="visible")
    return field


def _write_items(app, lesson_id: int, *texts: str) -> list[int]:
    """Put checklist items on a lesson the only way there is: type them into
    its note (§2 — "This table has no dedicated CRUD UI")."""
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        note = c.post("/api/notes/ensure", json={"lesson_id": lesson_id}).json()
        c.put(f"/api/notes/{note['id']}/blocks", json={"blocks": [
            {"id": None, "position": i, "block_type": "paragraph",
             "text": f"- [ ] {text}"}
            for i, text in enumerate(texts)
        ]})
    return [r[0] for r in app.query(
        "SELECT id FROM checklist_items ORDER BY position"
    )]


# --------------------------------------------------------------------------
# §7 The inline tree builder **[LOCKED]**
# --------------------------------------------------------------------------

def test_enter_adds_a_lesson_and_reopens_the_row(page_roadmap, roadmap_app) -> None:
    """"Typing text and pressing Enter creates the Lesson and immediately opens
    a fresh '+ Add lesson' row below it, so multiple lessons can be added in a
    fast burst without re-clicking anything.\""""
    page = page_roadmap
    field = _lesson_field(page, roadmap_app)

    field.click()
    for name in ["Window functions", "Two pointers", "Byte-pair encoding"]:
        page.keyboard.type(name)
        page.keyboard.press("Enter")
        page.wait_for_timeout(250)

    # Three lessons, added without ever reaching for the mouse again.
    names = [r[0] for r in roadmap_app.query(
        "SELECT name FROM lessons ORDER BY position"
    )]
    assert names == ["Window functions", "Two pointers", "Byte-pair encoding"]
    # The row is empty and still focused, ready for the next one.
    assert field.input_value() == ""
    assert field.evaluate("el => el === document.activeElement")


def test_a_new_lesson_opens_by_name(page_roadmap, roadmap_app) -> None:
    """Adding used to end in a Tab that jumped into the new lesson's note.
    There is no jump any more because there is nowhere to jump *from*: the row
    appears under the field as you type, and its name opens its page like
    every other name in the app."""
    page = page_roadmap
    field = _lesson_field(page, roadmap_app)
    field.click()
    page.keyboard.type("Window functions")
    page.keyboard.press("Enter")
    page.wait_for_timeout(400)

    lesson_id = roadmap_app.query("SELECT id FROM lessons")[0][0]
    page.get_by_test_id(f"lesson-name-{lesson_id}").click()
    page.get_by_test_id("page-screen").wait_for(state="visible", timeout=10_000)
    assert page.get_by_test_id("note-title").inner_text() == "Window functions"


def test_checklist_items_cannot_be_created_from_the_roadmap(page_roadmap,
                                                            roadmap_app) -> None:
    """§2 **[LOCKED]** — "This table has no dedicated CRUD UI." The Roadmap
    points at the note rather than offering an input of its own."""
    page = page_roadmap
    field = _lesson_field(page, roadmap_app)
    field.click()
    page.keyboard.type("Window functions")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)

    lesson_id = roadmap_app.query("SELECT id FROM lessons")[0][0]
    assert page.get_by_test_id(f"add-item-{lesson_id}").count() == 0

    _write_items(roadmap_app, lesson_id, "First")
    page.reload(wait_until="networkidle")
    page.get_by_test_id("nav-roadmap").click()
    page.get_by_test_id(f"lesson-chevron-{lesson_id}").click()
    page.get_by_test_id(f"lesson-write-items-{lesson_id}").wait_for(state="visible")


def test_there_is_no_create_dialog_anywhere(page_roadmap, roadmap_app) -> None:
    """"This is the entire authoring flow — no separate 'create' dialog, no
    modal.\""""
    page = page_roadmap
    field = _lesson_field(page, roadmap_app)
    field.click()
    page.keyboard.type("Inline only")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)

    assert page.locator('[role="dialog"]').count() == 0
    assert roadmap_app.query("SELECT count(*) FROM lessons")[0][0] == 1


# --------------------------------------------------------------------------
# §4 Rollup, in the browser
# --------------------------------------------------------------------------

def test_ticking_every_item_flips_the_lesson_and_moves_the_bars(page_roadmap,
                                                                 roadmap_app) -> None:
    page = page_roadmap
    sid = _subtopic_id(roadmap_app)
    field = _lesson_field(page, roadmap_app)
    field.click()
    page.keyboard.type("Window functions")
    page.keyboard.press("Enter")
    page.wait_for_timeout(250)

    lesson_id = roadmap_app.query("SELECT id FROM lessons")[0][0]
    item_ids = _write_items(roadmap_app, lesson_id, "First", "Second")

    page.reload(wait_until="networkidle")
    page.get_by_test_id("nav-roadmap").click()
    page.get_by_test_id("roadmap").wait_for(state="visible")
    page.get_by_test_id(f"lesson-chevron-{lesson_id}").click()

    page.get_by_test_id(f"item-{item_ids[0]}").click()
    page.wait_for_timeout(600)
    assert roadmap_app.query("SELECT status FROM lessons")[0][0] == "not_started"

    page.get_by_test_id(f"item-{item_ids[1]}").click()
    page.wait_for_function(
        f"() => document.querySelector('[data-testid=lesson-{lesson_id}]')"
        "?.dataset.status === 'done'",
        timeout=10_000,
    )
    assert roadmap_app.query("SELECT status FROM lessons")[0][0] == "done"


def test_an_empty_subject_shows_a_dash_not_zero_percent(page_roadmap) -> None:
    """Addendum §4 — "an empty subject shouldn't look '0% learned'"."""
    page = page_roadmap
    bar = page.get_by_test_id("progress-bar").first
    bar.wait_for(state="visible")
    assert bar.get_attribute("data-pct") == "none"
    assert "—" in bar.inner_text()
    assert "0%" not in bar.inner_text()


# --------------------------------------------------------------------------
# §5 Visual distinction from FSRS mastery **[LOCKED]**
# --------------------------------------------------------------------------

def test_progress_bars_carry_no_mastery_vocabulary(page_roadmap,
                                                    roadmap_app) -> None:
    """"This progress layer and the FSRS mastery badges … must not share a
    visual language … Conflating them would quietly teach the user that
    finishing a checklist is the same as knowing the material — exactly the
    wrong lesson for an app built around retrieval practice.\""""
    page = page_roadmap
    field = _lesson_field(page, roadmap_app)
    field.click()
    page.keyboard.type("Finished lesson")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)

    body = page.get_by_test_id("roadmap").inner_text().lower()
    for word in ["mastered", "fading", "untested", "mastery", "badge",
                 "retention", "recall"]:
        assert word not in body, f"{word!r} leaked into the progress layer"


def test_a_completed_bar_is_the_accent_not_green(page_roadmap,
                                                 roadmap_app) -> None:
    """"Use a plain percentage bar (grey track, single accent fill, no
    traffic-light colour semantics)". Green is reserved for Mastered."""
    page = page_roadmap
    field = _lesson_field(page, roadmap_app)
    field.click()
    page.keyboard.type("Done lesson")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)

    lesson_id = roadmap_app.query("SELECT id FROM lessons")[0][0]
    # not_started -> in_progress -> done
    page.get_by_test_id(f"lesson-status-{lesson_id}").click()
    page.wait_for_timeout(300)
    page.get_by_test_id(f"lesson-status-{lesson_id}").click()
    page.wait_for_function(
        f"() => document.querySelector('[data-testid=lesson-{lesson_id}]')"
        "?.dataset.status === 'done'", timeout=10_000,
    )

    fill_colour = page.evaluate(
        """() => {
          const bars = [...document.querySelectorAll('[data-testid=progress-bar]')]
          const full = bars.find(b => b.dataset.pct === '100')
          const fill = full?.querySelector('span > span > span')
          return fill ? getComputedStyle(fill).backgroundColor : null
        }"""
    )
    # The accent (#6B6BDC), never a mastery green.
    assert fill_colour == "rgb(107, 107, 220)", fill_colour


def test_the_roadmap_shows_completed_work(page_roadmap, roadmap_app) -> None:
    """"no hide-completed toggle here" — unlike Todos."""
    page = page_roadmap
    assert page.get_by_test_id("hide-completed").count() == 0


# --------------------------------------------------------------------------
# §6 Todos view
# --------------------------------------------------------------------------

def test_todos_combines_standalone_todos_with_open_lessons(page_roadmap,
                                                            roadmap_app) -> None:
    page = page_roadmap
    field = _lesson_field(page, roadmap_app)
    field.click()
    page.keyboard.type("An open lesson")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)

    page.get_by_test_id("nav-todos").click()
    page.get_by_test_id("todos").wait_for(state="visible")

    page.get_by_test_id("todo-input").fill("Redo resume")
    page.get_by_test_id("todo-add").click()
    page.wait_for_timeout(400)

    entries = page.get_by_test_id("todo-entries").inner_text()
    assert "Redo resume" in entries
    assert "An open lesson" in entries


def test_hide_completed_is_on_by_default_and_toggles(page_roadmap,
                                                      roadmap_app) -> None:
    """"This is the view with the hide-completed toggle, default on — its job
    is 'what's left'.\""""
    page = page_roadmap
    page.get_by_test_id("nav-todos").click()
    page.get_by_test_id("todos").wait_for(state="visible")

    toggle = page.get_by_test_id("hide-completed")
    assert toggle.is_checked()

    page.get_by_test_id("todo-input").fill("Finish this")
    page.get_by_test_id("todo-add").click()
    page.wait_for_timeout(400)

    todo_id = roadmap_app.query("SELECT id FROM todos")[0][0]
    page.get_by_test_id(f"entry-todo-{todo_id}").locator("input").click()
    page.wait_for_timeout(700)

    # Hidden while the toggle is on.
    assert page.get_by_test_id(f"entry-todo-{todo_id}").count() == 0

    toggle.uncheck()
    page.get_by_test_id(f"entry-todo-{todo_id}").wait_for(state="visible",
                                                          timeout=10_000)


def test_todos_does_not_scroll_sideways_when_narrow(page_roadmap) -> None:
    page = page_roadmap
    page.get_by_test_id("nav-todos").click()
    page.get_by_test_id("todos").wait_for(state="visible")
    page.set_viewport_size({"width": 500, "height": 900})
    page.wait_for_timeout(250)
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"page scrolls horizontally by {overflow}px at 500px"
