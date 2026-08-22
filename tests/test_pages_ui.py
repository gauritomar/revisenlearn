"""Pages, code blocks and deletion, in a real browser.

The user's model: "a Notion type interface where everything is a page and
pages under pages", the Roadmap as "the centralised way to access notes", and
code blocks with "syntax only for python, SQL etc".
"""

from __future__ import annotations

import httpx
import pytest

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
