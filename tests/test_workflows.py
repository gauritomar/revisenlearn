"""The four end-to-end user workflows for Phase 1.

Each workflow is covered twice:

* an **API + database** test, which is the assertion of record — it drives the
  real server and then reads the SQLite file directly to prove the state
  changed;
* a **UI** test (marked ``ui``), which drives the same built SPA that pywebview
  loads, in a real browser.

The UI tests skip cleanly if Playwright's Chromium is not installed. The API
tests always run.
"""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

from conftest import start_app

TODAY = dt.date.today().isoformat()


# ==========================================================================
# Workflow 1 — User starts the app
# ==========================================================================

def test_workflow_1_app_starts_with_an_empty_dashboard(app, client) -> None:
    assert client.get("/api/health").json()["status"] == "ok"

    meta = client.get("/api/meta").json()
    assert meta["app_name"] == "Revise & Learn"
    assert meta["phase"] == 1

    # The dashboard is empty: nothing has been created yet.
    assert client.get("/api/subjects").json() == []
    assert client.get(f"/api/notes/by-date/{TODAY}").json() == []

    # The shell itself is served, and the logo is a real image.
    index = client.get("/")
    assert index.status_code == 200
    assert "<div id=\"root\">" in index.text

    logo = client.get("/logo.png")
    assert logo.status_code == 200
    assert logo.headers["content-type"] == "image/png"
    assert logo.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(logo.content) > 1000


@pytest.mark.ui
def test_workflow_1_ui_window_shows_header_logo_and_title(page) -> None:
    # "Revise & Learn" is in the header.
    header = page.get_by_test_id("app-header")
    header.wait_for(state="visible")
    assert page.get_by_test_id("app-title").inner_text() == "Revise & Learn"

    # The logo is visible in the header AND actually decoded (a broken <img>
    # is still "visible" to a selector, so check the intrinsic width).
    logo = page.get_by_test_id("header-logo")
    logo.wait_for(state="visible")
    assert logo.evaluate("img => img.complete && img.naturalWidth > 0"), \
        "the header logo did not load"

    # The dashboard is showing, and it is empty.
    page.get_by_test_id("dashboard").wait_for(state="visible")
    page.get_by_test_id("sidebar-empty").wait_for(state="visible")
    assert page.get_by_test_id("subject-tree").count() == 0


@pytest.mark.ui
def test_workflow_1_ui_sidebar_renders_seeded_subjects(seeded_page) -> None:
    """Spec §18: Phase 1 is done when 'the window opens, the sidebar renders
    seeded subjects, migrations run clean'. This is that middle clause, in the
    browser rather than over the API."""
    tree = seeded_page.get_by_test_id("subject-tree")
    tree.wait_for(state="visible")

    seeded_page.get_by_test_id("subject-GenAI").wait_for(state="visible")
    assert seeded_page.locator('[data-testid^="subject-"]').count() >= 3

    # The tree really is a tree: expanding reveals topics, then subtopics.
    seeded_page.get_by_test_id("subject-GenAI").click()
    seeded_page.get_by_test_id("topic-Retrieval").wait_for(state="visible")
    seeded_page.get_by_test_id("topic-Retrieval").click()
    seeded_page.get_by_test_id("subtopic-Hybrid search").wait_for(state="visible")


# ==========================================================================
# Workflow 2 — User creates a subject, topic and subtopic
# ==========================================================================

def test_workflow_2_create_subject_topic_subtopic(app, client) -> None:
    subject = client.post("/api/subjects", json={"name": "GenAI"}).json()
    topic = client.post(
        "/api/topics", json={"subject_id": subject["id"], "name": "Retrieval"}
    ).json()
    subtopic = client.post(
        "/api/subtopics", json={"topic_id": topic["id"], "name": "Hybrid search"}
    ).json()

    # They appear in the tree the sidebar renders.
    tree = client.get("/api/subjects").json()
    assert [s["name"] for s in tree] == ["GenAI"]
    assert [t["name"] for t in tree[0]["topics"]] == ["Retrieval"]
    assert [st["name"] for st in tree[0]["topics"][0]["subtopics"]] == ["Hybrid search"]

    # They are in the database.
    assert app.query("SELECT name FROM subjects WHERE deleted_at IS NULL") == [("GenAI",)]
    assert app.query("SELECT name FROM topics WHERE deleted_at IS NULL") == [("Retrieval",)]
    assert app.query("SELECT name FROM subtopics WHERE deleted_at IS NULL") == [("Hybrid search",)]

    # The hierarchy is wired up, not three orphans.
    rows = app.query(
        "SELECT s.name, t.name, st.name "
        "FROM subtopics st "
        "JOIN topics t   ON t.id = st.topic_id "
        "JOIN subjects s ON s.id = t.subject_id"
    )
    assert rows == [("GenAI", "Retrieval", "Hybrid search")]
    assert subtopic["topic_id"] == topic["id"]


def test_workflow_2_delete_is_soft(app, client) -> None:
    """Principle §1.7 [LOCKED]: nothing is ever hard-deleted."""
    subject = client.post("/api/subjects", json={"name": "Temporary"}).json()
    topic = client.post(
        "/api/topics", json={"subject_id": subject["id"], "name": "Doomed"}
    ).json()

    assert client.delete(f"/api/subjects/{subject['id']}").status_code == 204

    assert client.get("/api/subjects").json() == []
    # The rows are still there, just stamped.
    assert app.query("SELECT count(*) FROM subjects")[0][0] == 1
    assert app.query("SELECT deleted_at IS NOT NULL FROM subjects")[0][0] == 1
    # The soft-delete cascades so children do not dangle in the tree.
    assert app.query(
        "SELECT deleted_at IS NOT NULL FROM topics WHERE id = ?", (topic["id"],)
    )[0][0] == 1


@pytest.mark.ui
def test_workflow_2_ui_add_via_sidebar_plus_button(page, app) -> None:
    # Click the "+" button in the left sidebar.
    page.get_by_test_id("sidebar-add").click()
    page.get_by_test_id("add-dialog").wait_for(state="visible")

    page.get_by_test_id("input-subject").fill("GenAI")
    page.get_by_test_id("input-topic").fill("Retrieval")
    page.get_by_test_id("input-subtopic").fill("Hybrid search")
    page.get_by_test_id("add-dialog-submit").click()

    # They appear in the tree in the sidebar (the dialog auto-expands them).
    page.get_by_test_id("subject-GenAI").wait_for(state="visible")
    page.get_by_test_id("topic-Retrieval").wait_for(state="visible")
    page.get_by_test_id("subtopic-Hybrid search").wait_for(state="visible")

    # They are in the database.
    assert app.query("SELECT name FROM subjects WHERE deleted_at IS NULL") == [("GenAI",)]
    assert app.query("SELECT name FROM topics WHERE deleted_at IS NULL") == [("Retrieval",)]
    assert app.query(
        "SELECT name FROM subtopics WHERE deleted_at IS NULL"
    ) == [("Hybrid search",)]


# ==========================================================================
# Workflow 3 — User takes a note (and it survives a restart)
# ==========================================================================

def _make_branch(client: httpx.Client) -> dict:
    subject = client.post("/api/subjects", json={"name": "GenAI"}).json()
    topic = client.post(
        "/api/topics", json={"subject_id": subject["id"], "name": "Retrieval"}
    ).json()
    subtopic = client.post(
        "/api/subtopics", json={"topic_id": topic["id"], "name": "Hybrid search"}
    ).json()
    return {"subject": subject, "topic": topic, "subtopic": subtopic}


def test_workflow_3_take_a_note_and_it_survives_a_restart(app, client, db_path) -> None:
    branch = _make_branch(client)

    # Clicking the subtopic opens today's note, created on the spot (§4.1).
    note = client.post(
        "/api/notes/ensure", json={"subtopic_id": branch["subtopic"]["id"]}
    ).json()
    assert note["study_date"] == TODAY
    assert note["title"] == "Hybrid search"
    # The note is filed under the whole branch, not just the subtopic.
    assert note["topic_id"] == branch["topic"]["id"]
    assert note["subject_id"] == branch["subject"]["id"]

    # Clicking again returns the same note rather than making a second one.
    again = client.post(
        "/api/notes/ensure", json={"subtopic_id": branch["subtopic"]["id"]}
    ).json()
    assert again["id"] == note["id"]

    # Type some bullet points and save.
    bullets = [
        "BM25 handles rare exact terms that embeddings miss",
        "Dense retrieval handles paraphrase",
        "Reciprocal rank fusion merges the two rankings",
    ]
    saved = client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [
            {"id": None, "position": i, "block_type": "bullet_list_item", "text": t}
            for i, t in enumerate(bullets)
        ]},
    ).json()

    assert [b["text"] for b in saved["blocks"]] == bullets
    # Spec §4.2 — never processed yet, so all three read as new.
    assert saved["counts"] == {"processed": 0, "new": 3, "edited": 0}
    assert all(b["state"] == "unprocessed" for b in saved["blocks"])
    assert all(b["content_hash"] for b in saved["blocks"])

    persisted = app.query(
        "SELECT text FROM note_blocks WHERE deleted_at IS NULL ORDER BY position"
    )
    assert [r[0] for r in persisted] == bullets

    # --- Close the app ---
    app.stop()

    # --- Reopen it on the same database ---
    reopened = start_app(db_path)
    try:
        with httpx.Client(base_url=reopened.base_url, timeout=30) as c2:
            # The note is still there.
            after = c2.get(f"/api/notes/{note['id']}").json()
            assert [b["text"] for b in after["blocks"]] == bullets
            assert after["study_date"] == TODAY
            assert after["title"] == "Hybrid search"

            # And it is still reachable the way the user got to it.
            same = c2.post(
                "/api/notes/ensure", json={"subtopic_id": branch["subtopic"]["id"]}
            ).json()
            assert same["id"] == note["id"]
            assert len(same["blocks"]) == 3
    finally:
        reopened.stop()


def test_workflow_3_editing_a_processed_block_marks_it_stale(app, client) -> None:
    """Spec §4.2 [LOCKED] — the three indicator states must be real."""
    branch = _make_branch(client)
    note = client.post(
        "/api/notes/ensure", json={"subtopic_id": branch["subtopic"]["id"]}
    ).json()

    saved = client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [
            {"id": None, "position": 0, "block_type": "bullet_list_item", "text": "Original text"},
            {"id": None, "position": 1, "block_type": "bullet_list_item", "text": "Untouched"},
        ]},
    ).json()
    block = saved["blocks"][0]
    assert block["state"] == "unprocessed"

    # Simulate the pipeline having processed both blocks (Phase 5 does this for
    # real; here we set the marker the same way it will).
    import sqlite3
    conn = sqlite3.connect(app.db_path)
    conn.execute("UPDATE note_blocks SET processed_hash = content_hash")
    conn.commit()
    conn.close()

    now_processed = client.get(f"/api/notes/{note['id']}").json()
    assert [b["state"] for b in now_processed["blocks"]] == ["processed", "processed"]
    assert now_processed["counts"] == {"processed": 2, "new": 0, "edited": 0}

    # Edit the first block. It must become stale, not new — the concepts derived
    # from it no longer reflect what it says.
    edited = client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [
            {"id": block["id"], "position": 0, "block_type": "bullet_list_item",
             "text": "Original text, now revised"},
            {"id": now_processed["blocks"][1]["id"], "position": 1,
             "block_type": "bullet_list_item", "text": "Untouched"},
        ]},
    ).json()

    assert [b["state"] for b in edited["blocks"]] == ["stale", "processed"]
    assert edited["counts"] == {"processed": 1, "new": 0, "edited": 1}


def test_workflow_3_whitespace_only_edit_does_not_go_stale(app, client) -> None:
    """content_hash is over *normalised* text (spec §4.2), so reflowing
    whitespace must not invalidate downstream concepts."""
    branch = _make_branch(client)
    note = client.post(
        "/api/notes/ensure", json={"subtopic_id": branch["subtopic"]["id"]}
    ).json()
    saved = client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [{"id": None, "position": 0, "block_type": "paragraph",
                          "text": "Hybrid search combines BM25 and dense retrieval"}]},
    ).json()
    block = saved["blocks"][0]

    import sqlite3
    conn = sqlite3.connect(app.db_path)
    conn.execute("UPDATE note_blocks SET processed_hash = content_hash")
    conn.commit()
    conn.close()

    respaced = client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [{"id": block["id"], "position": 0, "block_type": "paragraph",
                          "text": "  Hybrid search combines BM25   and dense retrieval  "}]},
    ).json()
    assert respaced["blocks"][0]["state"] == "processed"


@pytest.mark.ui
def test_workflow_3_ui_type_a_note_save_and_reopen(page, app, db_path, browser) -> None:
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        _make_branch(c)
    page.reload(wait_until="networkidle")

    # Click through to the subtopic.
    page.get_by_test_id("subject-GenAI").click()
    page.get_by_test_id("topic-Retrieval").click()
    page.get_by_test_id("subtopic-Hybrid search").click()

    # The editor pane opens with today's date.
    editor = page.get_by_test_id("note-editor")
    editor.wait_for(state="visible")
    assert page.get_by_test_id("note-title").inner_text() == "Hybrid search"
    assert page.get_by_test_id("note-date").get_attribute("datetime") == TODAY

    # Type some bullet points. "- " turns into a bullet list in Tiptap.
    editor.click()
    page.keyboard.type("- BM25 catches rare exact terms")
    page.keyboard.press("Enter")
    page.keyboard.type("Dense retrieval catches paraphrase")
    page.keyboard.press("Enter")
    page.keyboard.type("RRF merges the two rankings")

    # Hit Ctrl+S to force the save (spec §14.4).
    page.keyboard.press("Control+s")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=save-status]')"
        "?.dataset.state === 'saved'",
        timeout=10_000,
    )

    stored = [
        r[0] for r in app.query(
            "SELECT text FROM note_blocks WHERE deleted_at IS NULL ORDER BY position"
        )
    ]
    assert stored == [
        "BM25 catches rare exact terms",
        "Dense retrieval catches paraphrase",
        "RRF merges the two rankings",
    ]
    assert app.query(
        "SELECT DISTINCT block_type FROM note_blocks WHERE deleted_at IS NULL"
    ) == [("bullet_list_item",)]

    # --- Close and reopen the app ---
    app.stop()
    reopened = start_app(db_path)
    try:
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page2 = context.new_page()
        try:
            page2.goto(reopened.base_url, wait_until="networkidle")
            page2.get_by_test_id("subject-GenAI").click()
            page2.get_by_test_id("topic-Retrieval").click()
            page2.get_by_test_id("subtopic-Hybrid search").click()

            editor2 = page2.get_by_test_id("note-editor")
            editor2.wait_for(state="visible")
            # The note is still there.
            text = editor2.inner_text()
            assert "BM25 catches rare exact terms" in text
            assert "Dense retrieval catches paraphrase" in text
            assert "RRF merges the two rankings" in text
        finally:
            context.close()
    finally:
        reopened.stop()


@pytest.mark.ui
def test_workflow_3_ui_autosave_fires_without_pressing_anything(page, app) -> None:
    """Spec §4.1 — debounced 800ms after typing stops. No keystroke required."""
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        _make_branch(c)
    page.reload(wait_until="networkidle")

    page.get_by_test_id("subject-GenAI").click()
    page.get_by_test_id("topic-Retrieval").click()
    page.get_by_test_id("subtopic-Hybrid search").click()

    editor = page.get_by_test_id("note-editor")
    editor.wait_for(state="visible")
    editor.click()
    page.keyboard.type("Autosaved without pressing anything")

    # Wait only on the debounce, never touching the keyboard again.
    page.wait_for_function(
        "() => document.querySelector('[data-testid=save-status]')"
        "?.dataset.state === 'saved'",
        timeout=10_000,
    )

    stored = [r[0] for r in app.query(
        "SELECT text FROM note_blocks WHERE deleted_at IS NULL"
    )]
    assert stored == ["Autosaved without pressing anything"]


# ==========================================================================
# Workflow 4 — User can search
# ==========================================================================

def _seed_notes_with_text(client: httpx.Client) -> dict:
    """Notes already created, one of which says 'attention mechanism'."""
    branch = _make_branch(client)
    note = client.post(
        "/api/notes/ensure", json={"subtopic_id": branch["subtopic"]["id"]}
    ).json()
    client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [
            {"id": None, "position": 0, "block_type": "bullet_list_item",
             "text": "The attention mechanism lets each token weigh every other token"},
            {"id": None, "position": 1, "block_type": "bullet_list_item",
             "text": "BM25 is a sparse lexical scorer"},
        ]},
    )
    return {"branch": branch, "note": note}


def test_workflow_4_search_finds_a_note(app, client) -> None:
    seeded = _seed_notes_with_text(client)

    results = client.get("/api/search", params={"q": "attention"}).json()

    assert results["query"] == "attention"
    assert len(results["hits"]) >= 1
    hit = results["hits"][0]
    assert hit["kind"] == "note_block"
    assert hit["note_id"] == seeded["note"]["id"]
    assert hit["title"] == "Hybrid search"
    # FTS5 marks the matched term in the snippet.
    assert "<mark>attention</mark>" in hit["snippet"]

    # The non-matching block in the same note is not returned.
    assert not any("BM25" in h["snippet"] for h in results["hits"])


def test_workflow_4_search_is_prefix_and_stem_aware(app, client) -> None:
    _seed_notes_with_text(client)

    # Prefix: the palette matches as you type.
    assert client.get("/api/search", params={"q": "atten"}).json()["hits"]
    # Porter stemming: "mechanisms" finds "mechanism".
    assert client.get("/api/search", params={"q": "mechanisms"}).json()["hits"]
    # A term that is not there finds nothing.
    assert client.get("/api/search", params={"q": "transformerz"}).json()["hits"] == []


def test_workflow_4_search_handles_fts5_operators_as_plain_text(app, client) -> None:
    """A user typing 'AND', '*' or '-' into the palette must not get a 500."""
    _seed_notes_with_text(client)

    for query in ["attention AND", "attention*", "-attention", 'attention "', "OR", "NEAR("]:
        response = client.get("/api/search", params={"q": query})
        assert response.status_code == 200, f"{query!r} returned {response.status_code}"


def test_workflow_4_deleted_notes_leave_the_index(app, client) -> None:
    seeded = _seed_notes_with_text(client)
    assert client.get("/api/search", params={"q": "attention"}).json()["hits"]

    client.delete(f"/api/notes/{seeded['note']['id']}")

    assert client.get("/api/search", params={"q": "attention"}).json()["hits"] == []
    # Soft-deleted, not gone (principle §1.7).
    assert app.query("SELECT count(*) FROM note_blocks")[0][0] == 2


@pytest.mark.ui
def test_workflow_4_ui_command_palette_finds_the_note(page, app) -> None:
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        _seed_notes_with_text(c)
    page.reload(wait_until="networkidle")

    # Press Cmd/Ctrl+K.
    page.keyboard.press("Control+k")
    page.get_by_test_id("command-palette").wait_for(state="visible")

    page.get_by_test_id("palette-input").fill("attention")

    # The note appears in results.
    result = page.get_by_test_id("palette-result").first
    result.wait_for(state="visible", timeout=10_000)
    assert "Hybrid search" in result.inner_text()
    assert "attention" in result.inner_text().lower()

    # Clicking it opens that note.
    result.click()
    editor = page.get_by_test_id("note-editor")
    editor.wait_for(state="visible")
    assert "attention mechanism" in editor.inner_text()


@pytest.mark.ui
def test_workflow_4_ui_escape_closes_the_palette(page) -> None:
    """Spec §14.4 — Esc closes modals."""
    page.keyboard.press("Control+k")
    page.get_by_test_id("command-palette").wait_for(state="visible")
    page.keyboard.press("Escape")
    page.get_by_test_id("command-palette").wait_for(state="detached")


# ==========================================================================
# Responsive audit (spec §14.1 [LOCKED])
# ==========================================================================

@pytest.mark.ui
@pytest.mark.parametrize("width", [500, 650, 900, 1440])
def test_no_horizontal_scrolling_at_any_breakpoint(page, width: int) -> None:
    """Spec §14.1: 'No horizontal scrolling ever.' Tested at exactly the four
    widths the spec names."""
    page.set_viewport_size({"width": width, "height": 900})
    page.wait_for_timeout(250)

    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"page scrolls horizontally by {overflow}px at {width}px"

    # The header and its content stay put at every width.
    page.get_by_test_id("app-header").wait_for(state="visible")
    assert page.get_by_test_id("app-title").is_visible()


@pytest.mark.ui
def test_both_sidebars_collapse_below_900px(page) -> None:
    """Spec §14.1 [LOCKED]: 'Both sidebars auto-collapse below 900px.'"""
    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_timeout(250)
    assert page.get_by_test_id("left-sidebar").count() >= 1
    assert page.get_by_test_id("right-sidebar").count() >= 1

    page.set_viewport_size({"width": 899, "height": 900})
    page.wait_for_timeout(250)
    assert page.get_by_test_id("right-sidebar").count() == 0
