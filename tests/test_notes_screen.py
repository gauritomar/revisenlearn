"""The Notes screen (spec §14) and the parts of §4.1 it exposes.

"the editor, with the block indicators from §4.2 and a Process notes button in
the header showing the unprocessed count."

"One note per (Subtopic, day) by default, but the user can create additional
notes and rename them."
"""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

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
    return {"subject": subject, "topic": topic, "subtopic": subtopic}


def _open_subtopic(page) -> None:
    page.get_by_test_id("subject-GenAI").click()
    page.get_by_test_id("topic-Retrieval").click()
    page.get_by_test_id("subtopic-Hybrid search").click()
    page.get_by_test_id("note-editor").wait_for(state="visible")


# --------------------------------------------------------------------------
# API: renaming and additional notes (§4.1)
# --------------------------------------------------------------------------

def test_a_note_can_be_renamed(app, client) -> None:
    branch = _branch(app.base_url)
    note = client.post(
        "/api/notes/ensure", json={"subtopic_id": branch["subtopic"]["id"]}
    ).json()
    assert note["title"] == "Hybrid search"

    renamed = client.patch(
        f"/api/notes/{note['id']}", json={"title": "Hybrid search — BM25 vs dense"}
    ).json()

    assert renamed["title"] == "Hybrid search — BM25 vs dense"
    assert app.query("SELECT title FROM notes") == [("Hybrid search — BM25 vs dense",)]


def test_additional_notes_can_be_created_for_the_same_day(app, client) -> None:
    """§4.1 — one note per (Subtopic, day) *by default*, not as a limit."""
    branch = _branch(app.base_url)
    first = client.post(
        "/api/notes/ensure", json={"subtopic_id": branch["subtopic"]["id"]}
    ).json()
    second = client.post(
        "/api/notes",
        json={"subtopic_id": branch["subtopic"]["id"], "title": "Second pass"},
    ).json()

    assert second["id"] != first["id"]
    assert second["study_date"] == TODAY

    listed = client.get(
        "/api/notes",
        params={"subtopic_id": branch["subtopic"]["id"], "study_date": TODAY},
    ).json()
    assert {n["id"] for n in listed} == {first["id"], second["id"]}

    # `ensure` still returns the original, not the newest.
    again = client.post(
        "/api/notes/ensure", json={"subtopic_id": branch["subtopic"]["id"]}
    ).json()
    assert again["id"] == first["id"]


def test_renaming_a_note_does_not_touch_its_blocks(app, client) -> None:
    branch = _branch(app.base_url)
    note = client.post(
        "/api/notes/ensure", json={"subtopic_id": branch["subtopic"]["id"]}
    ).json()
    client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [{"id": None, "position": 0, "block_type": "paragraph",
                          "text": "Content that must survive"}]},
    )

    renamed = client.patch(f"/api/notes/{note['id']}", json={"title": "New name"}).json()

    assert renamed["title"] == "New name"
    assert [b["text"] for b in renamed["blocks"]] == ["Content that must survive"]


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

@pytest.mark.ui
def test_process_notes_button_shows_the_unprocessed_count(page, app) -> None:
    """Spec §14 — the button carries the count. The pipeline is Phase 5, so it
    must be visibly disabled rather than silently doing nothing."""
    _branch(app.base_url)
    page.reload(wait_until="networkidle")
    _open_subtopic(page)

    button = page.get_by_test_id("process-notes")
    assert button.is_visible()
    # Disabled only because there is nothing pending yet, not because the
    # pipeline is missing.
    assert button.is_disabled()
    assert button.get_attribute("data-pending") == "0"

    editor = page.get_by_test_id("note-editor")
    editor.click()
    page.keyboard.type("- One")
    page.keyboard.press("Enter")
    page.keyboard.type("Two")
    page.keyboard.press("Control+s")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=save-status]')"
        "?.dataset.state === 'saved'",
        timeout=10_000,
    )

    page.wait_for_function(
        "() => document.querySelector('[data-testid=process-notes]')"
        "?.dataset.pending === '2'",
        timeout=10_000,
    )
    assert "2" in button.inner_text()


@pytest.mark.ui
def test_process_notes_count_includes_edited_blocks(page, app) -> None:
    """§4.2 — a processed-then-edited block is work the pipeline still owes,
    so it counts alongside genuinely new ones."""
    import sqlite3

    branch = _branch(app.base_url)
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        note = c.post(
            "/api/notes/ensure", json={"subtopic_id": branch["subtopic"]["id"]}
        ).json()
        c.put(
            f"/api/notes/{note['id']}/blocks",
            json={"blocks": [
                {"id": None, "position": 0, "block_type": "paragraph", "text": "Alpha"},
                {"id": None, "position": 1, "block_type": "paragraph", "text": "Beta"},
            ]},
        )

    conn = sqlite3.connect(app.db_path)
    conn.execute("UPDATE note_blocks SET processed_hash = content_hash")
    conn.commit()
    conn.close()

    page.reload(wait_until="networkidle")
    _open_subtopic(page)

    # Both processed -> nothing pending.
    page.wait_for_function(
        "() => document.querySelector('[data-testid=process-notes]')"
        "?.dataset.pending === '0'",
        timeout=10_000,
    )

    # Edit one -> it becomes pending again.
    page.get_by_text("Alpha").click()
    page.keyboard.press("End")
    page.keyboard.type(" revised")
    page.keyboard.press("Control+s")

    page.wait_for_function(
        "() => document.querySelector('[data-testid=process-notes]')"
        "?.dataset.pending === '1'",
        timeout=10_000,
    )
    assert "1 edited" in page.get_by_test_id("block-counter").inner_text()


@pytest.mark.ui
def test_renaming_a_note_in_the_editor(page, app) -> None:
    _branch(app.base_url)
    page.reload(wait_until="networkidle")
    _open_subtopic(page)

    assert page.get_by_test_id("note-title").inner_text() == "Hybrid search"

    page.get_by_test_id("rename-note").click()
    field = page.get_by_test_id("note-title-input")
    field.wait_for(state="visible")
    field.fill("BM25 vs dense")
    page.keyboard.press("Enter")

    # The heading reappears with the old title before the PATCH resolves, so
    # wait on the text rather than on the element being visible.
    page.wait_for_function(
        "() => document.querySelector('[data-testid=note-title]')"
        "?.textContent === 'BM25 vs dense'",
        timeout=10_000,
    )
    assert app.query("SELECT title FROM notes") == [("BM25 vs dense",)]


@pytest.mark.ui
def test_escape_cancels_a_rename(page, app) -> None:
    _branch(app.base_url)
    page.reload(wait_until="networkidle")
    _open_subtopic(page)

    page.get_by_test_id("rename-note").click()
    field = page.get_by_test_id("note-title-input")
    field.wait_for(state="visible")
    field.fill("Discarded name")
    page.keyboard.press("Escape")

    page.get_by_test_id("note-title").wait_for(state="visible")
    assert page.get_by_test_id("note-title").inner_text() == "Hybrid search"
    page.wait_for_timeout(400)
    assert app.query("SELECT title FROM notes") == [("Hybrid search",)]


@pytest.mark.ui
def test_creating_and_switching_between_additional_notes(page, app) -> None:
    """§4.1 — additional notes for the same day, switchable."""
    _branch(app.base_url)
    page.reload(wait_until="networkidle")
    _open_subtopic(page)

    editor = page.get_by_test_id("note-editor")
    editor.click()
    page.keyboard.type("First note content")
    page.keyboard.press("Control+s")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=save-status]')"
        "?.dataset.state === 'saved'",
        timeout=10_000,
    )

    page.get_by_test_id("new-note").click()
    page.get_by_test_id("note-siblings").wait_for(state="visible", timeout=10_000)

    # The new note is empty and distinct.
    editor = page.get_by_test_id("note-editor")
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=note-editor]')"
        ".innerText.includes('First note content')",
        timeout=10_000,
    )
    editor.click()
    page.keyboard.type("Second note content")
    page.keyboard.press("Control+s")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=save-status]')"
        "?.dataset.state === 'saved'",
        timeout=10_000,
    )

    rows = app.query(
        "SELECT nb.text FROM note_blocks nb WHERE nb.deleted_at IS NULL ORDER BY nb.text"
    )
    assert rows == [("First note content",), ("Second note content",)]
    assert app.query("SELECT count(*) FROM notes WHERE deleted_at IS NULL")[0][0] == 2

    # Switch back to the first via the sibling pills.
    first_id = app.query("SELECT id FROM notes ORDER BY id")[0][0]
    page.get_by_test_id(f"sibling-{first_id}").click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=note-editor]')"
        ".innerText.includes('First note content')",
        timeout=10_000,
    )


@pytest.mark.ui
def test_a_resource_note_has_no_sibling_controls(page, app) -> None:
    """A resource note is one per resource per day, so "+ New note" would be
    meaningless there."""
    branch = _branch(app.base_url)
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        resource = c.post(
            "/api/resources",
            json={"title": "A video", "subtopic_id": branch["subtopic"]["id"]},
        ).json()

    page.reload(wait_until="networkidle")
    page.get_by_test_id(f"resource-{resource['id']}").first.click()
    page.get_by_test_id("note-editor").wait_for(state="visible")

    assert page.get_by_test_id("new-note").count() == 0
    assert page.get_by_test_id("note-siblings").count() == 0
    # But the Process notes button is still there — it is about blocks.
    assert page.get_by_test_id("process-notes").is_visible()
