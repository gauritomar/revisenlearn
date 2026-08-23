"""Pages, code blocks and deletion, in a real browser.

The user's model: "a Notion type interface where everything is a page and
pages under pages", the Roadmap as "the centralised way to access notes", and
code blocks with "syntax only for python, SQL etc".
"""

from __future__ import annotations

import httpx
import pytest

from conftest import wait_for_query

pytestmark = pytest.mark.ui


def _tree(base_url: str) -> dict:
    with httpx.Client(base_url=base_url, timeout=30) as c:
        subject = c.post("/api/subjects", json={"name": "DSA"}).json()
        topic = c.post("/api/topics", json={"subject_id": subject["id"],
                                            "name": "Codechef"}).json()
        subtopic = c.post("/api/subtopics", json={"topic_id": topic["id"],
                                                  "name": "Strings"}).json()
        note = c.post("/api/notes/ensure",
                      json={"subtopic_id": subtopic["id"]}).json()
        c.put(f"/api/notes/{note['id']}/blocks", json={"blocks": [
            {"id": None, "position": 0, "block_type": "bullet_list_item",
             "text": "ord() gives the code point"},
        ]})
    return {"subject": subject, "topic": topic, "subtopic": subtopic, "note": note}


def test_the_app_opens_on_the_roadmap(page, app) -> None:
    """"Let's keep just roadmap as a way to add notes … this is now the
    centralised way to access notes." So it is where the app starts, and
    Calendar and Notes no longer have tabs."""
    _tree(app.base_url)
    page.reload(wait_until="networkidle")

    page.get_by_test_id("roadmap").wait_for(state="visible")
    assert page.get_by_test_id("nav-calendar").count() == 0
    assert page.get_by_test_id("nav-notes").count() == 0
    # The calendar moved to the Dashboard, first thing on it.
    page.get_by_test_id("header-home").click()
    page.get_by_test_id("dash-calendar").wait_for(state="visible")


def test_a_subject_is_added_from_the_roadmap(page, app) -> None:
    page.reload(wait_until="networkidle")
    page.get_by_test_id("roadmap").wait_for(state="visible")

    page.get_by_test_id("roadmap-add-subject").click()
    page.get_by_test_id("roadmap-new-subject").fill("Systems")
    page.keyboard.press("Enter")

    page.wait_for_function(
        "() => !!document.querySelector('[data-testid^=\"roadmap-open-subject-\"]')",
        timeout=10_000,
    )
    assert app.query("SELECT name FROM subjects WHERE deleted_at IS NULL") == [("Systems",)]

    # The field stays open for a burst (addendum §7 [LOCKED]).
    page.keyboard.type("Mathematics")
    page.keyboard.press("Enter")
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid^=\"roadmap-open-subject-\"]').length === 2",
        timeout=10_000,
    )


def test_opening_a_page_shows_its_note_and_what_is_inside_it(page, app) -> None:
    tree = _tree(app.base_url)
    page.reload(wait_until="networkidle")
    page.get_by_test_id("roadmap").wait_for(state="visible")

    # A subject is a page too.
    page.get_by_test_id(f"roadmap-open-subject-{tree['subject']['id']}").click()
    page.get_by_test_id("page-screen").wait_for(state="visible")
    assert page.get_by_test_id("note-title").inner_text() == "DSA"
    inside = page.get_by_test_id("page-children").inner_text()
    assert "Codechef" in inside

    # …and the page inside it opens from there, with a trail back.
    page.get_by_test_id(f"page-child-topic-{tree['topic']['id']}").click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=note-title]')"
        "?.textContent === 'Codechef'", timeout=10_000)
    page.get_by_test_id(f"crumb-subject-{tree['subject']['id']}").click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=note-title]')"
        "?.textContent === 'DSA'", timeout=10_000)


def test_a_child_page_is_added_from_inside_its_parent(page, app) -> None:
    """"In the roadmap section i should be able to add subjects and everything
    easily" — and from the page itself, without going back to a tree."""
    tree = _tree(app.base_url)
    page.reload(wait_until="networkidle")
    page.get_by_test_id(f"roadmap-open-subtopic-{tree['subtopic']['id']}").click()
    page.get_by_test_id("page-screen").wait_for(state="visible")

    page.get_by_test_id("page-add-child").click()
    page.get_by_test_id("page-add-child-input").fill("Two pointers")
    page.keyboard.press("Enter")

    page.wait_for_function(
        "() => document.body.innerText.includes('Two pointers')", timeout=10_000)
    assert app.query("SELECT name FROM lessons WHERE deleted_at IS NULL") == \
        [("Two pointers",)]


def test_a_code_block_highlights_and_survives_a_reload(page, app) -> None:
    """"Within each notes app I should have the ability to add code blocks
    too, mostly syntax only for python, SQL etc." Typed with a fence, and it
    works inside a list — which is where most of these notes live."""
    tree = _tree(app.base_url)
    page.reload(wait_until="networkidle")
    page.get_by_test_id(f"roadmap-open-subtopic-{tree['subtopic']['id']}").click()
    page.get_by_test_id("page-screen").wait_for(state="visible")

    editor = page.get_by_test_id("note-editor")
    editor.click()
    page.keyboard.press("Control+End")
    page.keyboard.press("End")
    page.keyboard.press("Enter")          # a second bullet…
    page.keyboard.type("```python ")      # …which the fence lifts out of
    page.wait_for_timeout(250)
    page.keyboard.type("print(ord('A'))")

    block = page.locator("pre[data-language]")
    block.first.wait_for(state="visible", timeout=10_000)
    assert block.first.get_attribute("data-language") == "python"
    assert page.locator("pre .hljs-built_in, pre .hljs-string").count() > 0

    page.keyboard.press("Control+s")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=save-status]')"
        "?.dataset.state === 'saved'", timeout=10_000)
    assert app.query(
        "SELECT language FROM note_blocks WHERE block_type = 'code_block'"
    ) == [("python",)]

    page.reload(wait_until="networkidle")
    page.get_by_test_id("page-screen").wait_for(state="visible")
    reopened = page.locator("pre[data-language]")
    reopened.first.wait_for(state="visible", timeout=10_000)
    assert reopened.first.get_attribute("data-language") == "python"


def test_a_standalone_todo_can_be_deleted(page, app) -> None:
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        todo = c.post("/api/todos", json={"title": "Redo resume"}).json()

    page.reload(wait_until="networkidle")
    page.get_by_test_id("nav-todos").click()
    page.get_by_test_id("todos").wait_for(state="visible")

    row = page.get_by_test_id(f"entry-todo-{todo['id']}")
    row.wait_for(state="visible")
    row.hover()
    page.get_by_test_id(f"todo-delete-{todo['id']}").click()
    page.get_by_test_id(f"todo-delete-confirm-{todo['id']}").click()

    page.wait_for_function(
        f"() => !document.querySelector('[data-testid=\"entry-todo-{todo['id']}\"]')",
        timeout=10_000,
    )
    assert app.query("SELECT deleted_at IS NOT NULL FROM todos") == [(1,)]


def test_the_gemini_preview_links_to_the_note(page, app) -> None:
    """"When I get the 6 blocks to Gemini popup I should be able to click on
    the notes and go to them." """
    tree = _tree(app.base_url)
    page.reload(wait_until="networkidle")
    page.get_by_test_id("roadmap").wait_for(state="visible")

    page.get_by_test_id("process-notes").click()
    page.get_by_test_id("process-preview").wait_for(state="visible")
    opener = page.get_by_test_id(f"preview-open-subtopic-{tree['subtopic']['id']}")
    opener.wait_for(state="visible", timeout=10_000)
    opener.click()

    page.get_by_test_id("page-screen").wait_for(state="visible")
    assert page.get_by_test_id("note-title").inner_text() == "Strings"


def test_lesson_status_cycles_through_four_colours(page, app) -> None:
    """"Click on its done to do button and it will be highlighted in green and
    in-progress should be yellow, red if i need to return to it." Red is
    `revisit`, which is not the same as never having started."""
    tree = _tree(app.base_url)
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        c.post("/api/lessons", json={"topic_id": tree["topic"]["id"],
                                     "subtopic_id": tree["subtopic"]["id"],
                                     "name": "Roman numerals"})
    page.reload(wait_until="networkidle")
    page.get_by_test_id("roadmap").wait_for(state="visible")

    lesson_id = app.query("SELECT id FROM lessons")[0][0]
    row = page.get_by_test_id(f"lesson-{lesson_id}")
    row.wait_for(state="visible")

    for expected in ("in_progress", "done", "revisit", "not_started"):
        page.get_by_test_id(f"lesson-status-{lesson_id}").click()
        page.wait_for_function(
            f"() => document.querySelector('[data-testid=lesson-{lesson_id}]')"
            f"?.dataset.status === '{expected}'",
            timeout=8_000,
        )
    assert app.query("SELECT status FROM lessons")[0][0] == "not_started"


def test_a_subject_collapses_in_the_roadmap(page, app) -> None:
    tree = _tree(app.base_url)
    page.reload(wait_until="networkidle")
    page.get_by_test_id("roadmap").wait_for(state="visible")
    page.get_by_test_id(f"roadmap-topic-{tree['topic']['id']}").wait_for(state="visible")

    page.get_by_test_id(f"roadmap-collapse-subject-{tree['subject']['id']}").click()
    page.wait_for_function(
        f"() => !document.querySelector('[data-testid=\"roadmap-topic-{tree['topic']['id']}\"]')",
        timeout=8_000,
    )

    # …and it stays folded across a reload.
    page.reload(wait_until="networkidle")
    page.get_by_test_id("roadmap").wait_for(state="visible")
    page.wait_for_timeout(500)
    assert page.get_by_test_id(f"roadmap-topic-{tree['topic']['id']}").count() == 0


def test_a_page_carries_the_link_it_came_from(page, app) -> None:
    """"I should be able to link certain articles or youtube lectures or
    leetcode questions … and that link should be displayed when its page is
    open." It belongs to the page, not to the note."""
    tree = _tree(app.base_url)
    page.reload(wait_until="networkidle")
    page.get_by_test_id(f"roadmap-open-subtopic-{tree['subtopic']['id']}").click()
    page.get_by_test_id("page-screen").wait_for(state="visible")

    page.get_by_test_id("page-link-add").click()
    page.get_by_test_id("page-link-input").fill("https://www.codechef.com/roadmap/strings")
    page.keyboard.press("Enter")

    link = page.get_by_test_id("page-link")
    link.wait_for(state="visible", timeout=8_000)
    assert link.get_attribute("href") == "https://www.codechef.com/roadmap/strings"
    assert app.query("SELECT url FROM subtopics")[0][0] == \
        "https://www.codechef.com/roadmap/strings"

    # It is the page's, not the note's: nothing extra to send to the model.
    assert app.query(
        "SELECT count(*) FROM note_blocks WHERE text LIKE '%codechef%'"
    )[0][0] == 0


def test_a_section_can_be_added_without_scrolling(page, app) -> None:
    """"I want to be able to add blocks at a time as my notes are kind of
    random as i come across a concept i just add it.\""""
    tree = _tree(app.base_url)
    page.reload(wait_until="networkidle")
    page.get_by_test_id(f"roadmap-open-subtopic-{tree['subtopic']['id']}").click()
    page.get_by_test_id("page-screen").wait_for(state="visible")
    # Wait for the stored note to be in the editor before adding to it.
    page.wait_for_function(
        "() => document.querySelector('[data-testid=note-editor]')"
        "?.innerText.includes('ord()')",
        timeout=10_000,
    )

    page.get_by_test_id("add-section-top").click()
    # The section lands, and the cursor moves into its heading, on the next
    # render — type into the button and the keystrokes go nowhere.
    # Tiptap moves the caret into the new heading a tick after the insert, so
    # wait for the editor to actually hold it rather than typing into the gap.
    page.wait_for_function(
        "() => document.activeElement?.dataset?.testid === 'note-editor'"
        " && !!document.querySelector('[data-testid=note-editor] h3')",
        timeout=8_000,
    )
    page.keyboard.type("Sliding window")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=note-editor] h3')"
        "?.textContent === 'Sliding window'",
        timeout=8_000,
    )
    # A heading with bullets under it, at the top where the newest thing goes.
    html = page.get_by_test_id("note-editor").inner_html()
    assert html.index("<h3>") < html.index("ord()")


def test_the_note_is_twelve_point_sans(page, app) -> None:
    """"Make the text small like 12 pt and change the font to something else i
    like the google docs/notion standard font.\""""
    tree = _tree(app.base_url)
    page.reload(wait_until="networkidle")
    page.get_by_test_id(f"roadmap-open-subtopic-{tree['subtopic']['id']}").click()
    page.get_by_test_id("note-editor").wait_for(state="visible")

    style = page.evaluate(
        """() => {
          const s = getComputedStyle(document.querySelector('[data-testid=note-editor]'))
          return {size: parseFloat(s.fontSize), family: s.fontFamily.toLowerCase()}
        }"""
    )
    assert style["size"] == 15          # 12pt at 96dpi
    assert "serif" not in style["family"].replace("sans-serif", "")


def test_the_roadmap_survives_a_narrow_window(page, app) -> None:
    """"Even when i reduce the size of the window width, it should still have
    atleast roadmap on the header as for dashboard i can just click on Revise
    & Learn.\""""
    _tree(app.base_url)
    page.reload(wait_until="networkidle")
    page.set_viewport_size({"width": 700, "height": 900})
    page.wait_for_timeout(300)

    assert page.get_by_test_id("nav-roadmap").is_visible()
    assert page.get_by_test_id("header-home").is_visible()


def test_todos_can_be_deleted_and_bulk_managed(page, app) -> None:
    """"On the todos page I should be able to delete todos as well. and also
    have a select all.\""""
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        for title in ("Redo resume", "Book flights", "Read the paper"):
            c.post("/api/todos", json={"title": title})

    page.reload(wait_until="networkidle")
    page.get_by_test_id("nav-todos").click()
    page.get_by_test_id("todo-entries").wait_for(state="visible")
    ids = [r[0] for r in app.query("SELECT id FROM todos ORDER BY id")]

    # The per-row delete is visible without hunting for it.
    trash = page.get_by_test_id(f"todo-delete-{ids[0]}")
    assert trash.evaluate("el => getComputedStyle(el).opacity") == "1"
    trash.click()
    page.get_by_test_id(f"todo-delete-confirm-{ids[0]}").click()
    page.wait_for_function(
        f"() => !document.querySelector('[data-testid=\"entry-todo-{ids[0]}\"]')",
        timeout=10_000,
    )

    # Select all, then finish the rest in one go. Selecting is a mode, so a
    # row never shows two checkboxes at once.
    page.get_by_test_id("todo-select-mode").click()
    page.get_by_test_id("todo-select-all").check()
    page.get_by_test_id("todo-selection").wait_for(state="visible")
    page.get_by_test_id("todo-bulk-done").click()

    # Done todos drop off the board, which hides completed by default.
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid^=\"entry-todo-\"]').length === 0",
        timeout=10_000,
    )
    assert app.query(
        "SELECT count(*) FROM todos WHERE done = 1 AND deleted_at IS NULL"
    )[0][0] == 2


def test_selected_todos_can_be_deleted_together(page, app) -> None:
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        for title in ("One", "Two"):
            c.post("/api/todos", json={"title": title})

    page.reload(wait_until="networkidle")
    page.get_by_test_id("nav-todos").click()
    page.get_by_test_id("todo-entries").wait_for(state="visible")

    page.get_by_test_id("todo-select-mode").click()
    page.get_by_test_id("todo-select-all").check()
    page.get_by_test_id("todo-bulk-delete").click()

    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid^=\"entry-todo-\"]').length === 0",
        timeout=10_000,
    )
    assert app.query(
        "SELECT count(*) FROM todos WHERE deleted_at IS NOT NULL"
    )[0][0] == 2


def test_a_todo_row_never_shows_two_checkboxes(page, app) -> None:
    """"The todos have 2 tickboxes now, one to select and one to cross — this
    is confusing." One at a time: normally it completes the todo, and in
    Select mode it selects."""
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        c.post("/api/todos", json={"title": "Redo resume"})

    page.reload(wait_until="networkidle")
    page.get_by_test_id("nav-todos").click()
    page.get_by_test_id("todo-entries").wait_for(state="visible")
    todo_id = app.query("SELECT id FROM todos")[0][0]

    row = page.get_by_test_id(f"entry-todo-{todo_id}")
    assert row.locator("input[type=checkbox]").count() == 1
    assert page.get_by_test_id(f"done-todo-{todo_id}").count() == 1
    assert page.get_by_test_id(f"select-todo-{todo_id}").count() == 0

    page.get_by_test_id("todo-select-mode").click()
    page.get_by_test_id(f"select-todo-{todo_id}").wait_for(state="visible")
    assert row.locator("input[type=checkbox]").count() == 1
    assert page.get_by_test_id(f"done-todo-{todo_id}").count() == 0

    # Leaving the mode puts the completion box back.
    page.get_by_test_id("todo-select-done").click()
    page.get_by_test_id(f"done-todo-{todo_id}").wait_for(state="visible")


def test_resources_is_a_page_you_write_on(page, app) -> None:
    """"Let's not keep it as boxes rather just a place to write a note … just
    a blank page to write and save resources I want to work on later." """
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        c.post("/api/resources", json={"title": "NeetCode roadmap",
                                       "url": "https://neetcode.io/roadmap"})

    page.reload(wait_until="networkidle")
    page.get_by_test_id("nav-resources").click()
    page.get_by_test_id("resource-list").wait_for(state="visible")

    # A note, not a filing system.
    page.get_by_test_id("note-editor").wait_for(state="visible")
    assert page.get_by_test_id("note-title").inner_text() == "Resources"
    for gone in ("add-group", "tag-filters", "filter-active", "add-resource"):
        assert page.get_by_test_id(gone).count() == 0, gone

    # What was already saved came across, and can be edited like any line.
    page.wait_for_function(
        "() => document.querySelector('[data-testid=note-editor]')"
        "?.innerText.includes('NeetCode roadmap')",
        timeout=10_000,
    )

    editor = page.get_by_test_id("note-editor")
    editor.click()
    page.keyboard.press("Control+End")
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.keyboard.type("Read the KMP chapter")
    page.keyboard.press("Control+s")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=save-status]')"
        "?.dataset.state === 'saved'",
        timeout=10_000,
    )

    # Written down, and still not something to be examined on.
    assert app.query(
        "SELECT count(*) FROM note_blocks nb JOIN notes n ON n.id = nb.note_id "
        "WHERE n.scratch_key = 'resources' AND nb.text LIKE '%KMP%'"
    )[0][0] == 1
    page.get_by_test_id("process-notes").wait_for(state="visible")
    assert page.get_by_test_id("process-notes").get_attribute("data-pending") == "0"


def _seeded_concepts(app) -> None:
    """Notes processed by the mock provider, so there are real sets to show."""
    import time as _time

    with httpx.Client(base_url=app.base_url, timeout=120) as c:
        s = c.post("/api/subjects", json={"name": "DSA"}).json()
        t = c.post("/api/topics", json={"subject_id": s["id"], "name": "Codechef"}).json()
        st = c.post("/api/subtopics", json={"topic_id": t["id"], "name": "Strings"}).json()
        lesson = c.post("/api/lessons", json={
            "topic_id": t["id"], "subtopic_id": st["id"], "name": "Roman numerals",
        }).json()
        note = c.post("/api/notes/ensure", json={"lesson_id": lesson["id"]}).json()
        c.put(f"/api/notes/{note['id']}/blocks", json={"blocks": [
            {"id": None, "position": 0, "block_type": "bullet_list_item",
             "text": "Subtract when a smaller numeral precedes a larger one."},
        ]})
        job = c.post("/api/pipeline/run", json={}).json()
        for _ in range(120):
            body = c.get(f"/api/pipeline/jobs/{job['id']}").json()
            if body["job"]["status"] in ("succeeded", "failed"):
                break
            _time.sleep(0.5)
        assert body["job"]["status"] == "succeeded", body["job"].get("error_text")


@pytest.fixture
def mock_app(db_path):
    """An app whose model calls are the deterministic mock — no spend."""
    from conftest import start_app

    instance = start_app(db_path, extra_env={"RNL_LLM_PROVIDER": "mock"})
    try:
        yield instance
    finally:
        instance.stop()


@pytest.fixture
def mock_page(browser, mock_app):
    from conftest import _open_page

    yield from _open_page(browser, mock_app)


def test_practice_offers_a_set_per_place_studied(mock_page, mock_app) -> None:
    """"On the MCQ page I should have some tests ready based on the
    topics/subtopics/lessons I've already done … based on my recency of
    notes.\""""
    _seeded_concepts(mock_app)
    page = mock_page
    page.reload(wait_until="networkidle")
    page.get_by_test_id("nav-practice").click()

    sets = page.get_by_test_id("practice-sets")
    sets.wait_for(state="visible", timeout=20_000)
    text = sets.inner_text()
    assert "Roman numerals" in text
    assert "Codechef › Strings" in text          # where it sits
    assert "written today" in text               # recency

    # Starting one runs only that set's questions.
    page.locator('[data-testid^="set-lesson-"]').first.click()
    page.get_by_test_id("practice-runner").wait_for(state="visible", timeout=20_000)
    concept = page.get_by_test_id("practice-concept").inner_text()
    assert concept


def test_revision_offers_the_same_places(mock_page, mock_app) -> None:
    """"On the Revision panel also I should have topic-wise / subtopic
    revision ready." And the wait for a generated question is visible."""
    _seeded_concepts(mock_app)
    page = mock_page
    page.reload(wait_until="networkidle")
    page.get_by_test_id("nav-revision").click()

    sets = page.get_by_test_id("revision-sets")
    sets.wait_for(state="visible", timeout=20_000)
    assert "Roman numerals" in sets.inner_text()

    page.locator('[data-testid^="set-lesson-"]').first.click()
    # A model call is in flight, and says so.
    page.get_by_test_id("waiting").wait_for(state="visible", timeout=10_000)
    page.get_by_test_id("revision-runner").wait_for(state="visible", timeout=30_000)


def test_the_two_verdicts_are_told_apart_by_colour(mock_page, mock_app) -> None:
    """"Add colour to the I got this to green and I didn't get it to red,
    slightly colour only." §9.6 still forbids escalation, so it is a wash and
    a border rather than a filled red button."""
    _seeded_concepts(mock_app)
    page = mock_page
    page.reload(wait_until="networkidle")
    page.get_by_test_id("nav-revision").click()
    page.get_by_test_id("revision-sets").wait_for(state="visible", timeout=20_000)
    page.locator('[data-testid^="set-lesson-"]').first.click()
    page.get_by_test_id("revision-runner").wait_for(state="visible", timeout=30_000)

    page.get_by_test_id("revision-answer").fill("Compare each numeral with the next one.")
    page.get_by_test_id("revision-submit").click()
    page.get_by_test_id("override-got-it").wait_for(state="visible", timeout=30_000)

    got = page.get_by_test_id("override-got-it").evaluate(
        "el => getComputedStyle(el).color")
    wrong = page.get_by_test_id("override-wrong").evaluate(
        "el => getComputedStyle(el).color")
    assert got != wrong


def test_the_gemini_popup_lists_sections_and_remembers_what_you_untick(page, app) -> None:
    """"When the send to Gemini pop up comes up I should be able to choose all
    the blocks/sections that [are] going for processing" — and a section
    parked today should still be parked tomorrow."""
    tree = _tree(app.base_url)
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        note = c.post("/api/notes/ensure",
                      json={"subtopic_id": tree["subtopic"]["id"]}).json()
        blocks = [
            ("heading3", "String Functions"),
            ("bullet_list_item", "Roman numerals: subtract when a smaller value "
                                 "precedes a larger one, otherwise add it."),
            ("bullet_list_item", "ord() converts a character to its Unicode value."),
            ("heading3", "Knuth-Morris-Pratt / Rabin-Karp"),
            ("bullet_list_item", "https://codechef.com/problems/ZFUNCTION"),
            ("bullet_list_item", "https://codechef.com/problems/SHORTPALINDR"),
        ]
        c.put(f"/api/notes/{note['id']}/blocks", json={"blocks": [
            {"id": None, "position": i, "block_type": bt, "text": text}
            for i, (bt, text) in enumerate(blocks)
        ]})

    page.reload(wait_until="networkidle")
    page.get_by_test_id("process-notes").click()
    page.get_by_test_id("preview-sections").wait_for(state="visible")
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid^=\"preview-section-\"]').length === 2",
        timeout=10_000,
    )

    listed = page.get_by_test_id("preview-sections").inner_text()
    assert "String Functions" in listed
    assert "Knuth-Morris-Pratt" in listed

    keys = page.evaluate(
        """() => [...document.querySelectorAll('[data-testid^=preview-section-]')]
             .map(e => e.dataset.testid.replace('preview-section-', ''))"""
    )
    page.get_by_test_id(f"preview-toggle-{keys[1]}").click()
    page.wait_for_function(
        f"() => document.querySelector('[data-testid=\"preview-section-{keys[1]}\"]')"
        f"?.dataset.skipped === 'true'",
        timeout=10_000,
    )
    wait_for_query(
        app, "SELECT count(*) FROM note_blocks WHERE skip_processing = 1", [(3,)])

    # Escape closes it, and reopening remembers.
    page.keyboard.press("Escape")
    page.get_by_test_id("process-notes").wait_for(state="visible")
    page.get_by_test_id("process-notes").click()
    page.wait_for_function(
        f"() => document.querySelector('[data-testid=\"preview-section-{keys[1]}\"]')"
        f"?.dataset.skipped === 'true'",
        timeout=10_000,
    )
