"""The calendar month view (spec §14).

"Calendar (Apple-style month view with topic pills per day, click to open that
day)."
"""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

TODAY = dt.date.today()
TODAY_ISO = TODAY.isoformat()
THIS_MONTH = TODAY.strftime("%Y-%m")


def _tree(client) -> dict:
    subject = client.post(
        "/api/subjects", json={"name": "GenAI", "colour": "#6366F1"}
    ).json()
    retrieval = client.post(
        "/api/topics", json={"subject_id": subject["id"], "name": "Retrieval"}
    ).json()
    evaluation = client.post(
        "/api/topics", json={"subject_id": subject["id"], "name": "Evaluation"}
    ).json()
    hybrid = client.post(
        "/api/subtopics", json={"topic_id": retrieval["id"], "name": "Hybrid search"}
    ).json()
    judge = client.post(
        "/api/subtopics", json={"topic_id": evaluation["id"], "name": "LLM-as-judge"}
    ).json()
    return {
        "subject": subject, "retrieval": retrieval, "evaluation": evaluation,
        "hybrid": hybrid, "judge": judge,
    }


def _open_calendar(page) -> None:
    """The calendar lives on the Dashboard now — it lost its own tab, because
    the Roadmap is the way into notes and the calendar is a summary, not a
    destination."""
    page.get_by_test_id("header-home").click()
    page.get_by_test_id("dash-calendar").wait_for(state="visible")


def _note_on(client, subtopic_id: int, day: dt.date, text: str = "Something learned") -> dict:
    """A note *with writing in it*.

    The calendar shows days work happened, and since opening a page creates
    its note, an empty note is a visit rather than work — so the fixture has
    to write something for the day to count.
    """
    note = client.post(
        "/api/notes",
        json={"subtopic_id": subtopic_id, "study_date": day.isoformat()},
    ).json()
    if text:
        client.put(f"/api/notes/{note['id']}/blocks", json={"blocks": [
            {"id": None, "position": 0, "block_type": "paragraph", "text": text},
        ]})
    return note


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

def test_an_empty_note_is_not_a_day_of_work(client) -> None:
    """Opening a page creates its note. "If a change has been made to specific
    notes where proper blocks have been added only then it should be added to
    the calendar."
    """
    tree = _tree(client)
    _note_on(client, tree["hybrid"]["id"], TODAY, text="")

    assert client.get(f"/api/notes/calendar/{THIS_MONTH}").json()["days"] == []

    # Write something and the day appears.
    _note_on(client, tree["judge"]["id"], TODAY)
    days = client.get(f"/api/notes/calendar/{THIS_MONTH}").json()["days"]
    assert [d["date"] for d in days] == [TODAY_ISO]


def test_a_note_on_a_deleted_page_leaves_the_calendar(client) -> None:
    """Deleting a subtopic does not delete its notes (§1.7), but they are
    gone from the user's point of view — and so from the calendar."""
    tree = _tree(client)
    _note_on(client, tree["hybrid"]["id"], TODAY)
    assert client.get(f"/api/notes/calendar/{THIS_MONTH}").json()["days"]

    client.delete(f"/api/subtopics/{tree['hybrid']['id']}")
    assert client.get(f"/api/notes/calendar/{THIS_MONTH}").json()["days"] == []


def test_empty_month_returns_no_days(client) -> None:
    body = client.get(f"/api/notes/calendar/{THIS_MONTH}").json()
    assert body["month"] == THIS_MONTH
    assert body["days"] == []


def test_a_day_reports_its_note_count_and_topic_pills(client) -> None:
    tree = _tree(client)
    _note_on(client, tree["hybrid"]["id"], TODAY)
    _note_on(client, tree["judge"]["id"], TODAY)

    body = client.get(f"/api/notes/calendar/{THIS_MONTH}").json()

    assert len(body["days"]) == 1
    day = body["days"][0]
    assert day["date"] == TODAY_ISO
    assert day["note_count"] == 2
    # One pill per distinct topic, carrying the subject's colour.
    assert sorted(p["name"] for p in day["topics"]) == ["Evaluation", "Retrieval"]
    assert {p["colour"] for p in day["topics"]} == {"#6366F1"}


def test_two_notes_in_one_topic_produce_one_pill(client) -> None:
    tree = _tree(client)
    second = client.post(
        "/api/subtopics", json={"topic_id": tree["retrieval"]["id"], "name": "Chunking"}
    ).json()
    _note_on(client, tree["hybrid"]["id"], TODAY)
    _note_on(client, second["id"], TODAY)

    day = client.get(f"/api/notes/calendar/{THIS_MONTH}").json()["days"][0]
    assert day["note_count"] == 2
    assert [p["name"] for p in day["topics"]] == ["Retrieval"]


def test_only_the_requested_month_is_returned(client) -> None:
    tree = _tree(client)
    first_of_month = TODAY.replace(day=1)
    last_month_day = first_of_month - dt.timedelta(days=1)
    next_month_day = (first_of_month + dt.timedelta(days=32)).replace(day=1)

    _note_on(client, tree["hybrid"]["id"], first_of_month)
    _note_on(client, tree["hybrid"]["id"], last_month_day)
    _note_on(client, tree["hybrid"]["id"], next_month_day)

    body = client.get(f"/api/notes/calendar/{first_of_month.strftime('%Y-%m')}").json()
    returned = {d["date"] for d in body["days"]}

    assert first_of_month.isoformat() in returned
    assert last_month_day.isoformat() not in returned
    assert next_month_day.isoformat() not in returned


def test_december_rolls_over_to_january(client) -> None:
    """The month-end boundary is computed, not hardcoded — December must not
    ask for month 13."""
    tree = _tree(client)
    _note_on(client, tree["hybrid"]["id"], dt.date(2025, 12, 31))
    _note_on(client, tree["hybrid"]["id"], dt.date(2026, 1, 1))

    body = client.get("/api/notes/calendar/2025-12").json()
    assert [d["date"] for d in body["days"]] == ["2025-12-31"]


def test_deleted_notes_leave_the_calendar(client) -> None:
    tree = _tree(client)
    note = _note_on(client, tree["hybrid"]["id"], TODAY)

    assert client.get(f"/api/notes/calendar/{THIS_MONTH}").json()["days"]
    client.delete(f"/api/notes/{note['id']}")
    assert client.get(f"/api/notes/calendar/{THIS_MONTH}").json()["days"] == []


def test_a_malformed_month_is_a_400(client) -> None:
    for bad in ["2026", "2026-13-01", "not-a-month", "2026-xx"]:
        assert client.get(f"/api/notes/calendar/{bad}").status_code == 400


def test_a_resource_note_appears_on_the_calendar(client) -> None:
    """A note written against a resource still belongs to a day."""
    tree = _tree(client)
    resource = client.post(
        "/api/resources",
        json={"title": "RAG video", "subtopic_id": tree["hybrid"]["id"]},
    ).json()
    note = client.post("/api/notes/ensure",
                       json={"resource_id": resource["id"]}).json()
    client.put(f"/api/notes/{note['id']}/blocks", json={"blocks": [
        {"id": None, "position": 0, "block_type": "paragraph",
         "text": "Watched the first half"},
    ]})

    day = client.get(f"/api/notes/calendar/{THIS_MONTH}").json()["days"][0]
    assert day["note_count"] == 1
    assert [p["name"] for p in day["topics"]] == ["Retrieval"]


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

@pytest.mark.ui
def test_calendar_renders_the_current_month_with_pills(page, app) -> None:
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        tree = _tree(c)
        _note_on(c, tree["hybrid"]["id"], TODAY)

    page.reload(wait_until="networkidle")
    _open_calendar(page)
    calendar = page.get_by_test_id("calendar")
    calendar.wait_for(state="visible")

    expected = TODAY.strftime("%B %Y")
    assert page.get_by_test_id("calendar-month").inner_text() == expected

    cell = page.get_by_test_id(f"calendar-day-{TODAY_ISO}")
    assert cell.get_attribute("data-has-notes") == "true"
    assert "Retrieval" in cell.inner_text()


@pytest.mark.ui
def test_days_without_notes_are_not_clickable(page, app) -> None:
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        _tree(c)

    page.reload(wait_until="networkidle")
    _open_calendar(page)
    page.get_by_test_id("calendar").wait_for(state="visible")

    assert page.get_by_test_id(f"calendar-day-{TODAY_ISO}").is_disabled()


@pytest.mark.ui
def test_clicking_a_day_opens_that_day(page, app) -> None:
    """Spec §14 — "click to open that day"."""
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        tree = _tree(c)
        note = _note_on(c, tree["hybrid"]["id"], TODAY)
        c.put(
            f"/api/notes/{note['id']}/blocks",
            json={"blocks": [{"id": None, "position": 0, "block_type": "paragraph",
                              "text": "Reciprocal rank fusion"}]},
        )

    page.reload(wait_until="networkidle")
    _open_calendar(page)
    page.get_by_test_id("calendar").wait_for(state="visible")
    page.get_by_test_id(f"calendar-day-{TODAY_ISO}").click()

    day_view = page.get_by_test_id("day-view")
    day_view.wait_for(state="visible")
    assert "Hybrid search" in day_view.inner_text()
    assert "Reciprocal rank fusion" in day_view.inner_text()

    # And from there into the note itself.
    page.get_by_test_id(f"day-note-{note['id']}").click()
    editor = page.get_by_test_id("note-editor")
    editor.wait_for(state="visible")
    assert "Reciprocal rank fusion" in editor.inner_text()


@pytest.mark.ui
def test_month_navigation(page, app) -> None:
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        _tree(c)

    page.reload(wait_until="networkidle")
    _open_calendar(page)
    page.get_by_test_id("calendar").wait_for(state="visible")

    this_month = TODAY.strftime("%B %Y")
    previous = (TODAY.replace(day=1) - dt.timedelta(days=1)).strftime("%B %Y")

    page.get_by_test_id("calendar-prev").click()
    page.wait_for_function(
        f"() => document.querySelector('[data-testid=calendar-month]')"
        f".textContent === {previous!r}",
        timeout=5000,
    )

    page.get_by_test_id("calendar-today").click()
    page.wait_for_function(
        f"() => document.querySelector('[data-testid=calendar-month]')"
        f".textContent === {this_month!r}",
        timeout=5000,
    )


@pytest.mark.ui
@pytest.mark.parametrize("width", [500, 900])
def test_calendar_does_not_cause_horizontal_scroll(page, app, width: int) -> None:
    """Seven columns of pills is the most likely thing to blow out the
    narrow layout §14.1 cares about."""
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        tree = _tree(c)
        _note_on(c, tree["hybrid"]["id"], TODAY)
        _note_on(c, tree["judge"]["id"], TODAY)

    page.set_viewport_size({"width": width, "height": 900})
    page.reload(wait_until="networkidle")
    _open_calendar(page)
    page.get_by_test_id("calendar").wait_for(state="visible")

    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"page scrolls horizontally by {overflow}px at {width}px"
