"""The resource flow in a real browser (spec §5.1).

The API-level behaviour lives in `test_resources.py`; these tests hold the
interaction itself — paste a link, get a resource, click it, write against it.
"""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

from conftest import open_lesson

pytestmark = pytest.mark.ui

TODAY = dt.date.today().isoformat()


def _branch(base_url: str) -> dict:
    with httpx.Client(base_url=base_url, timeout=30) as c:
        subject = c.post("/api/subjects", json={"name": "GenAI"}).json()
        topic = c.post(
            "/api/topics", json={"subject_id": subject["id"], "name": "Retrieval"}
        ).json()
        subtopic = c.post(
            "/api/subtopics", json={"topic_id": topic["id"], "name": "Hybrid search"}
        ).json()
        # §3 — a note is opened by clicking a Lesson, so the branch has one.
        lesson = c.post("/api/lessons", json={
            "topic_id": topic["id"], "subtopic_id": subtopic["id"],
            "name": "Hybrid retrieval in practice",
        }).json()
    return {"subject": subject, "topic": topic, "subtopic": subtopic,
            "lesson": lesson}


def _dashboard(page) -> None:
    """Consolidated addendum §7 — the app opens on Calendar now. Everything
    below is about the dashboard's resource surfaces, so each test says so
    rather than relying on where the app happens to land."""
    page.get_by_test_id("header-home").click()
    page.get_by_test_id("dashboard").wait_for(state="visible")



def test_add_a_resource_by_pasting_a_link(page, app) -> None:
    """§5.1 — a single input, and Enter saves it."""
    _dashboard(page)
    page.get_by_test_id("dash-add-resource").click()
    page.get_by_test_id("resource-add").wait_for(state="visible")

    page.get_by_test_id("resource-input").fill("https://example.com/rag-course")
    page.get_by_test_id("resource-add-submit").click()

    page.get_by_test_id("resource-add").wait_for(state="detached")

    rows = app.query("SELECT title, url, resource_type, status FROM resources")
    assert rows == [(
        "https://example.com/rag-course",
        "https://example.com/rag-course",
        "article",
        "inbox",
    )]


def test_add_a_resource_by_typing_a_title(page, app) -> None:
    _dashboard(page)
    page.get_by_test_id("dash-add-resource").click()
    page.get_by_test_id("resource-input").fill("Work through CLRS chapter 4")
    page.get_by_test_id("resource-add-submit").click()
    page.get_by_test_id("resource-add").wait_for(state="detached")

    assert app.query("SELECT title, url FROM resources") == [
        ("Work through CLRS chapter 4", None)
    ]


def test_enter_submits_the_quick_add(page, app) -> None:
    """Five seconds means not reaching for the mouse."""
    _dashboard(page)
    page.get_by_test_id("dash-add-resource").click()
    page.get_by_test_id("resource-input").fill("Skim the FSRS paper")
    page.keyboard.press("Enter")
    page.get_by_test_id("resource-add").wait_for(state="detached")

    assert app.query("SELECT count(*) FROM resources")[0][0] == 1


def test_quick_add_placement_defaults_to_last_used(page, app) -> None:
    """§5.1 — pickers default to the last-used values."""
    branch = _branch(app.base_url)
    page.reload(wait_until="networkidle")
    _dashboard(page)

    # First add: choose a placement explicitly.
    page.get_by_test_id("dash-add-resource").click()
    page.get_by_test_id("resource-input").fill("First video")
    page.get_by_test_id("resource-subject").select_option(str(branch["subject"]["id"]))
    page.get_by_test_id("resource-topic").select_option(str(branch["topic"]["id"]))
    page.get_by_test_id("resource-subtopic").select_option(str(branch["subtopic"]["id"]))
    page.get_by_test_id("resource-add-submit").click()
    page.get_by_test_id("resource-add").wait_for(state="detached")

    # Second add: the pickers come back already filled in.
    page.get_by_test_id("dash-add-resource").click()
    page.get_by_test_id("resource-add").wait_for(state="visible")
    assert page.get_by_test_id("resource-subject").input_value() == str(branch["subject"]["id"])
    assert page.get_by_test_id("resource-subtopic").input_value() == str(branch["subtopic"]["id"])

    page.get_by_test_id("resource-input").fill("Second video")
    page.get_by_test_id("resource-add-submit").click()
    page.get_by_test_id("resource-add").wait_for(state="detached")

    placements = app.query(
        "SELECT title, subtopic_id FROM resources ORDER BY id"
    )
    assert placements == [
        ("First video", branch["subtopic"]["id"]),
        ("Second video", branch["subtopic"]["id"]),
    ]


def test_the_topic_picker_is_gated_on_the_subject(page, app) -> None:
    _branch(app.base_url)
    page.reload(wait_until="networkidle")
    _dashboard(page)

    page.get_by_test_id("dash-add-resource").click()
    page.get_by_test_id("resource-add").wait_for(state="visible")

    assert page.get_by_test_id("resource-topic").is_disabled()
    assert page.get_by_test_id("resource-subtopic").is_disabled()


def test_clicking_a_resource_opens_the_split_view(page, app) -> None:
    """§5.1 — left: metadata, status, progress, Open link.
              right: the note for that resource and today."""
    branch = _branch(app.base_url)
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        resource = c.post(
            "/api/resources",
            json={"url": "https://example.com/rag", "title": "RAG from scratch",
                  "subtopic_id": branch["subtopic"]["id"], "status": "in_progress"},
        ).json()

    page.reload(wait_until="networkidle")
    _dashboard(page)
    page.get_by_test_id(f"resource-{resource['id']}").first.click()

    split = page.get_by_test_id("resource-split")
    split.wait_for(state="visible")
    assert page.get_by_test_id("resource-title").inner_text() == "RAG from scratch"
    assert page.get_by_test_id("open-link").is_visible()
    assert page.get_by_test_id("resource-status").input_value() == "in_progress"

    # The right-hand side is today's note for this resource, created on the spot.
    page.get_by_test_id("note-editor").wait_for(state="visible")
    assert page.get_by_test_id("note-date").get_attribute("datetime") == TODAY
    assert page.get_by_test_id("note-title").inner_text() == "RAG from scratch"

    note_rows = app.query(
        "SELECT resource_id, study_date FROM notes WHERE deleted_at IS NULL"
    )
    assert note_rows == [(resource["id"], TODAY)]


def test_writing_in_the_resource_note_persists(page, app) -> None:
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        resource = c.post(
            "/api/resources", json={"title": "Attention paper"}
        ).json()

    page.reload(wait_until="networkidle")
    _dashboard(page)
    page.get_by_test_id(f"resource-{resource['id']}").first.click()
    editor = page.get_by_test_id("note-editor")
    editor.wait_for(state="visible")

    editor.click()
    page.keyboard.type("- Softmax over scaled dot products")
    page.keyboard.press("Control+s")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=save-status]')"
        "?.dataset.state === 'saved'",
        timeout=10_000,
    )

    rows = app.query(
        "SELECT nb.text, n.resource_id FROM note_blocks nb "
        "JOIN notes n ON n.id = nb.note_id WHERE nb.deleted_at IS NULL"
    )
    assert rows == [("Softmax over scaled dot products", resource["id"])]


def test_status_change_from_the_split_view(page, app) -> None:
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        resource = c.post("/api/resources", json={"title": "A course"}).json()

    page.reload(wait_until="networkidle")
    _dashboard(page)
    page.get_by_test_id(f"resource-{resource['id']}").first.click()
    page.get_by_test_id("resource-status").wait_for(state="visible")

    page.get_by_test_id("resource-status").select_option("completed")

    page.wait_for_function(
        "() => document.querySelector('[data-testid=resource-status]').value === 'completed'",
        timeout=10_000,
    )
    # Completion stamps completed_at and fills progress to 100 (spec §5).
    page.wait_for_timeout(400)
    assert app.query(
        "SELECT status, progress_pct, completed_at IS NOT NULL FROM resources"
    ) == [("completed", 100, 1)]


def test_progress_note_is_saved_on_blur(page, app) -> None:
    """§5 — free-text progress note, set by hand."""
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        resource = c.post("/api/resources", json={"title": "Long book"}).json()

    page.reload(wait_until="networkidle")
    _dashboard(page)
    page.get_by_test_id(f"resource-{resource['id']}").first.click()
    note_field = page.get_by_test_id("progress-note")
    note_field.wait_for(state="visible")

    note_field.fill("stopped at chapter 4")
    note_field.blur()

    page.wait_for_timeout(600)
    assert app.query("SELECT progress_note FROM resources") == [("stopped at chapter 4",)]


def test_a_resource_note_and_a_subtopic_note_do_not_collide(page, app) -> None:
    """Opening the subtopic and opening a resource filed under it are two
    different writing surfaces on the same day."""
    branch = _branch(app.base_url)
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        resource = c.post(
            "/api/resources",
            json={"title": "A video", "subtopic_id": branch["subtopic"]["id"]},
        ).json()

    page.reload(wait_until="networkidle")
    _dashboard(page)

    # Write in the subtopic's own note.
    open_lesson(page, "GenAI", "Retrieval", "Hybrid search",
                "Hybrid retrieval in practice")
    page.get_by_test_id("note-editor").wait_for(state="visible")
    page.get_by_test_id("note-editor").click()
    page.keyboard.type("Subtopic note text")
    page.keyboard.press("Control+s")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=save-status]')"
        "?.dataset.state === 'saved'",
        timeout=10_000,
    )

    # Now open the resource. It must be a different, empty note.
    page.get_by_test_id("nav-dashboard").click()
    page.get_by_test_id(f"resource-{resource['id']}").first.click()
    page.get_by_test_id("resource-split").wait_for(state="visible")
    editor = page.get_by_test_id("note-editor")
    editor.wait_for(state="visible")
    assert "Subtopic note text" not in editor.inner_text()

    editor.click()
    page.keyboard.type("Resource note text")
    page.keyboard.press("Control+s")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=save-status]')"
        "?.dataset.state === 'saved'",
        timeout=10_000,
    )

    rows = app.query(
        "SELECT n.resource_id, nb.text FROM note_blocks nb "
        "JOIN notes n ON n.id = nb.note_id "
        "WHERE nb.deleted_at IS NULL ORDER BY nb.text"
    )
    assert rows == [
        (resource["id"], "Resource note text"),
        (None, "Subtopic note text"),
    ]


def test_dashboard_shows_study_next_and_continue_learning(page, app) -> None:
    """Spec §14 Dashboard sections, with real data."""
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        c.post("/api/resources", json={"title": "Half watched", "status": "in_progress"})
        c.post("/api/resources", json={"title": "Queued up", "status": "next"})

    page.reload(wait_until="networkidle")
    _dashboard(page)

    continuing = page.get_by_test_id("dash-continue-learning")
    continuing.wait_for(state="visible")
    assert "Half watched" in continuing.inner_text()

    study_next = page.get_by_test_id("dash-study-next")
    assert "Half watched" in study_next.inner_text()
    assert "Queued up" in study_next.inner_text()
    # Started work outranks queued work.
    text = study_next.inner_text()
    assert text.index("Half watched") < text.index("Queued up")


def test_dashboard_todays_notes_lists_what_was_written(page, app) -> None:
    branch = _branch(app.base_url)
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        note = c.post(
            "/api/notes/ensure", json={"subtopic_id": branch["subtopic"]["id"]}
        ).json()
        c.put(
            f"/api/notes/{note['id']}/blocks",
            json={"blocks": [{"id": None, "position": 0,
                              "block_type": "paragraph", "text": "Something learned"}]},
        )

    page.reload(wait_until="networkidle")
    _dashboard(page)
    section = page.get_by_test_id("dash-todays-notes")
    section.wait_for(state="visible")
    assert "Hybrid search" in section.inner_text()
    assert "1 block" in section.inner_text()

    # Clicking it opens that note.
    page.get_by_test_id(f"todays-note-{note['id']}").click()
    page.get_by_test_id("note-editor").wait_for(state="visible")
    assert "Something learned" in page.get_by_test_id("note-editor").inner_text()


def test_right_sidebar_shows_the_current_resource(page, app) -> None:
    """Spec §14 — the right sidebar in Notes shows the current resource. The
    consolidated addendum §6 moved it under the Links tab, first in the list
    and marked as this note's own."""
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        resource = c.post(
            "/api/resources",
            json={"title": "Dense retrieval lecture", "status": "in_progress"},
        ).json()
        c.patch(
            f"/api/resources/{resource['id']}",
            json={"progress_pct": 60, "progress_note": "stopped at 22:15"},
        )

    page.reload(wait_until="networkidle")
    _dashboard(page)
    page.get_by_test_id(f"resource-{resource['id']}").first.click()
    page.get_by_test_id("resource-split").wait_for(state="visible")

    page.get_by_test_id("right-tab-resources").click()
    panel = page.get_by_test_id("sidebar-resource")
    panel.wait_for(state="visible", timeout=10_000)
    text = panel.inner_text()
    assert "Dense retrieval lecture" in text
    assert "60%" in text
    assert "stopped at 22:15" in text


def test_the_links_tab_is_empty_for_a_note_with_no_urls(page, app) -> None:
    """Consolidated addendum §6 — the right panel is tabbed now, and Links
    lists what §4 detected. A note with no URLs has nothing there, and says
    what would put something there."""
    branch = _branch(app.base_url)
    page.reload(wait_until="networkidle")

    open_lesson(page, "GenAI", "Retrieval", "Hybrid search",
                "Hybrid retrieval in practice")

    page.get_by_test_id("right-tab-resources").click()
    sidebar = page.get_by_test_id("right-sidebar")
    assert "No links here yet" in sidebar.inner_text()
    assert page.get_by_test_id("resources-tab").count() == 0
    assert branch["subtopic"]["name"] == "Hybrid search"
