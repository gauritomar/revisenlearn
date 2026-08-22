"""The Notion-style sidebar and the tabbed right panel (consolidated addendum
§5 and §6), in the browser.

"clicking a page's **chevron** expands children inline without navigating;
clicking the **name** navigates to open that page. Replicate that distinction
exactly."
"""

from __future__ import annotations

import httpx
import pytest

from conftest import expand_row, open_lesson

LESSON = "Hybrid retrieval in practice"


def _tree(base_url: str) -> dict:
    with httpx.Client(base_url=base_url, timeout=30) as c:
        subject = c.post("/api/subjects", json={"name": "GenAI"}).json()
        topic = c.post("/api/topics", json={"subject_id": subject["id"],
                                            "name": "Retrieval"}).json()
        subtopic = c.post("/api/subtopics", json={"topic_id": topic["id"],
                                                  "name": "Hybrid search"}).json()
        lesson = c.post("/api/lessons", json={
            "topic_id": topic["id"], "subtopic_id": subtopic["id"], "name": LESSON,
        }).json()
    return {"subject": subject, "topic": topic, "subtopic": subtopic,
            "lesson": lesson}


# --------------------------------------------------------------------------
# §5 — chevron expands, name navigates
# --------------------------------------------------------------------------

@pytest.mark.ui
def test_a_subjects_name_does_not_expand_it(page, app) -> None:
    """"Clicking the row's **name** does nothing for these three levels
    (they're organizational, not navigable)."""
    _tree(app.base_url)
    page.reload(wait_until="networkidle")

    page.get_by_test_id("subject-GenAI").wait_for(state="visible")
    subject_id = app.query("SELECT id FROM subjects")[0][0]
    page.get_by_test_id(f"subject-name-{subject_id}").click()
    assert page.get_by_test_id("topic-Retrieval").count() == 0

    # The chevron does.
    page.get_by_test_id(f"subject-chevron-{subject_id}").click()
    page.get_by_test_id("topic-Retrieval").wait_for(state="visible")


@pytest.mark.ui
def test_a_lessons_name_opens_its_note_as_a_route(page, app) -> None:
    """§3 — "real page navigation (e.g. route `/lessons/{id}`), not an inline
    pane swap"; §5 — "clicking a **Lesson's name** navigates into its note"."""
    tree = _tree(app.base_url)
    page.reload(wait_until="networkidle")

    open_lesson(page, "GenAI", "Retrieval", "Hybrid search", LESSON)

    assert page.get_by_test_id("note-title").inner_text() == LESSON
    assert page.url.endswith(f"#/lessons/{tree['lesson']['id']}")
    # The breadcrumb says where it sits, since the note has no name of its own.
    assert "Hybrid search" in page.get_by_test_id("note-breadcrumb").inner_text()

    # Back leaves the note, exactly as a route should.
    page.go_back()
    page.get_by_test_id("note-editor").wait_for(state="detached")


@pytest.mark.ui
def test_a_row_is_deleted_behind_one_confirmation(page, app) -> None:
    """§5 — "hovering any row … reveals a small trash icon … behind one
    confirmation step."""
    _tree(app.base_url)
    page.reload(wait_until="networkidle")
    subject_id = app.query("SELECT id FROM subjects")[0][0]

    row = page.get_by_test_id("subject-GenAI")
    row.wait_for(state="visible")
    trash = page.get_by_test_id(f"subject-delete-{subject_id}")

    # Hidden until the row is hovered, and never destructive on first click.
    assert trash.evaluate("el => getComputedStyle(el).opacity") == "0"
    row.hover()
    page.wait_for_function(
        f"() => getComputedStyle(document.querySelector("
        f"'[data-testid=\"subject-delete-{subject_id}\"]')).opacity === '1'"
    )
    trash.click()
    assert app.query("SELECT deleted_at IS NULL FROM subjects")[0][0] == 1

    page.get_by_test_id(f"subject-delete-confirm-{subject_id}").click()
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"subject-GenAI\"]')"
    )
    assert app.query("SELECT deleted_at IS NOT NULL FROM subjects")[0][0] == 1
    # "deletes that item and its children" — soft, per principle §1.7.
    assert app.query("SELECT deleted_at IS NOT NULL FROM topics")[0][0] == 1
    assert app.query("SELECT deleted_at IS NOT NULL FROM subtopics")[0][0] == 1


@pytest.mark.ui
def test_a_lesson_can_be_dragged_onto_another_subtopic(page, app) -> None:
    """§5 — drag-and-drop reordering "updating each item's `position` column".
    Dropping a lesson on a subtopic moves it inside."""
    tree = _tree(app.base_url)
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        c.post("/api/subtopics", json={"topic_id": tree["topic"]["id"],
                                       "name": "Embeddings"})
    page.reload(wait_until="networkidle")

    expand_row(page, "subject", "GenAI")
    expand_row(page, "topic", "Retrieval")
    expand_row(page, "subtopic", "Hybrid search")

    page.get_by_test_id(f"sidebar-lesson-{LESSON}").drag_to(
        page.get_by_test_id("subtopic-Embeddings")
    )

    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"sidebar-lesson-"
        + LESSON + "\"]')",
        timeout=10_000,
    )
    moved = app.query("SELECT subtopic_id FROM lessons")[0][0]
    assert moved != tree["subtopic"]["id"]

    # It stays moved: the drag wrote `position`/parent, not view state.
    page.reload(wait_until="networkidle")
    expand_row(page, "subject", "GenAI")
    expand_row(page, "topic", "Retrieval")
    expand_row(page, "subtopic", "Embeddings")
    page.get_by_test_id(f"sidebar-lesson-{LESSON}").wait_for(state="visible")


@pytest.mark.ui
def test_quick_add_creates_a_lesson_without_walking_the_tree(page, app) -> None:
    """§5 — "This must work without first expanding/collapsing down through the
    tree to reach the right spot."""
    tree = _tree(app.base_url)
    page.reload(wait_until="networkidle")

    page.get_by_test_id("sidebar-add").click()
    page.get_by_test_id("add-dialog").wait_for(state="visible")
    page.get_by_test_id("input-name").fill("Reranking")
    page.get_by_test_id(f"add-parent-subtopic-{tree['subtopic']['id']}").click()
    page.get_by_test_id("add-dialog-submit").click()

    # A new lesson is somewhere to write, so it opens.
    page.get_by_test_id("note-editor").wait_for(state="visible")
    assert page.get_by_test_id("note-title").inner_text() == "Reranking"
    assert ("Reranking",) in app.query("SELECT name FROM lessons")


@pytest.mark.ui
def test_the_command_palette_reaches_the_quick_add(page, app) -> None:
    """§5 — the quick-add is "reachable via ⌘K", carrying what was typed."""
    _tree(app.base_url)
    page.reload(wait_until="networkidle")

    page.keyboard.press("Meta+k")
    page.get_by_test_id("command-palette").wait_for(state="visible")
    page.get_by_test_id("palette-input").fill("Sparse retrieval")
    # The button renders the query, so wait on that rather than on the
    # keystroke: clicking before React has re-rendered reads an empty query.
    page.wait_for_function(
        "() => document.querySelector('[data-testid=palette-add]')"
        "?.textContent.includes('Sparse retrieval')",
        timeout=5000,
    )
    page.get_by_test_id("palette-add").click()

    page.get_by_test_id("add-dialog").wait_for(state="visible")
    # The name is filled in by an effect, so it lands a frame after the dialog.
    page.wait_for_function(
        "() => document.querySelector('[data-testid=input-name]')"
        "?.value === 'Sparse retrieval'",
        timeout=5000,
    )


# --------------------------------------------------------------------------
# §6 — the right panel is tabbed, checklist first
# --------------------------------------------------------------------------

@pytest.mark.ui
def test_the_checklist_tab_toggles_through_to_the_note(page, app) -> None:
    """§6.1 — "click to toggle (writes through to the note block, per §2)"."""
    tree = _tree(app.base_url)
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        note = c.post("/api/notes/ensure",
                      json={"lesson_id": tree["lesson"]["id"]}).json()
        c.put(f"/api/notes/{note['id']}/blocks", json={"blocks": [
            {"id": None, "position": 0, "block_type": "paragraph",
             "text": "- [ ] Read the chunking paper"},
        ]})
    page.reload(wait_until="networkidle")
    open_lesson(page, "GenAI", "Retrieval", "Hybrid search", LESSON)

    # Checklist is the default tab whenever the lesson has items.
    page.get_by_test_id("checklist-tab").wait_for(state="visible")
    item_id = app.query("SELECT id FROM checklist_items")[0][0]
    page.get_by_test_id(f"panel-item-{item_id}").click()

    page.wait_for_function(
        "() => document.querySelector('[data-testid=\"right-tab-checklist\"]')",
    )
    page.wait_for_timeout(600)
    assert app.query("SELECT checked FROM note_blocks")[0][0] == 1
    assert app.query("SELECT checked FROM checklist_items")[0][0] == 1


@pytest.mark.ui
def test_the_panel_tabs_switch_without_losing_the_note(page, app) -> None:
    tree = _tree(app.base_url)
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        c.post("/api/notes/ensure", json={"lesson_id": tree["lesson"]["id"]})
    page.reload(wait_until="networkidle")
    open_lesson(page, "GenAI", "Retrieval", "Hybrid search", LESSON)

    page.get_by_test_id("right-tab-pipeline").click()
    page.get_by_test_id("pipeline-tab").wait_for(state="visible")
    page.get_by_test_id("right-tab-resources").click()
    page.get_by_test_id("note-editor").wait_for(state="visible")


@pytest.mark.ui
def test_a_url_in_the_note_shows_up_under_links(page, app) -> None:
    """§6.3 — "links referenced in this note (from §4's auto-detection)"."""
    tree = _tree(app.base_url)
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        note = c.post("/api/notes/ensure",
                      json={"lesson_id": tree["lesson"]["id"]}).json()
        c.put(f"/api/notes/{note['id']}/blocks", json={"blocks": [
            {"id": None, "position": 0, "block_type": "paragraph",
             "text": "https://example.com/chunking"},
        ]})
    page.reload(wait_until="networkidle")
    open_lesson(page, "GenAI", "Retrieval", "Hybrid search", LESSON)

    page.get_by_test_id("right-tab-resources").click()
    resource_id = app.query("SELECT id FROM resources")[0][0]
    page.get_by_test_id(f"panel-resource-{resource_id}").wait_for(state="visible")


@pytest.mark.ui
def test_below_900_the_panels_overlay_one_at_a_time(page, app) -> None:
    """§6 — "Below ~900px width, both side panels collapse to icon toggles in
    the header, overlay-style, one open at a time"."""
    tree = _tree(app.base_url)
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        c.post("/api/notes/ensure", json={"lesson_id": tree["lesson"]["id"]})
    page.reload(wait_until="networkidle")
    page.set_viewport_size({"width": 880, "height": 900})
    page.wait_for_timeout(250)

    assert page.get_by_test_id("left-sidebar").count() == 0
    assert page.get_by_test_id("right-sidebar").count() == 0

    page.get_by_test_id("toggle-left-sidebar").click()
    page.get_by_test_id("overlay-left").wait_for(state="visible")

    # Opening the other closes the first: the note stays the dominant element.
    page.get_by_test_id("toggle-right-sidebar").click()
    page.get_by_test_id("overlay-right").wait_for(state="visible")
    assert page.get_by_test_id("overlay-left").count() == 0

    page.get_by_test_id("toggle-right-sidebar").click()
    page.get_by_test_id("overlay-right").wait_for(state="detached")


@pytest.mark.ui
def test_typing_a_checkbox_reaches_the_right_panel(page, app) -> None:
    """§10's own check: "Type `- [ ] test item` in that note → it appears in
    the right panel Checklist tab; check it there → the note's checkbox
    updates too."""
    tree = _tree(app.base_url)
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        c.post("/api/notes/ensure", json={"lesson_id": tree["lesson"]["id"]})
    page.reload(wait_until="networkidle")
    open_lesson(page, "GenAI", "Retrieval", "Hybrid search", LESSON)

    editor = page.get_by_test_id("note-editor")
    editor.click()
    page.keyboard.type("- [ ] test item")
    page.keyboard.press("Control+s")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=save-status]')"
        "?.dataset.state === 'saved'",
        timeout=10_000,
    )

    # The editor turned it into a real checkbox, not literal text.
    assert page.locator("ul[data-type='taskList'] li").count() == 1

    item = page.locator('[data-testid^="panel-item-"]')
    item.first.wait_for(state="visible", timeout=10_000)
    item.first.click()

    page.wait_for_timeout(600)
    assert app.query("SELECT checked FROM note_blocks")[0][0] == 1
    assert app.query(
        "SELECT block_type FROM note_blocks"
    )[0][0] == "checklist_item"
