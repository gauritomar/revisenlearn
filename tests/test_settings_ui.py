"""The Settings screen in a real browser (spec §14, §17).

§17 puts "Back up now" and the Markdown export here, so this is where Phase 3
becomes reachable by a user rather than only by curl.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.ui


def _open_settings(page):
    page.get_by_test_id("nav-settings").click()
    page.get_by_test_id("settings").wait_for(state="visible")


def test_settings_is_reachable_from_the_header(page) -> None:
    assert page.get_by_test_id("nav-settings").is_enabled()
    _open_settings(page)
    assert "Settings" in page.get_by_test_id("settings").inner_text()


def test_settings_reports_key_presence_but_never_the_key(page, app) -> None:
    """Spec §17 — the key must not cross this boundary."""
    _open_settings(page)

    status = page.get_by_test_id("api-key-status")
    assert status.is_visible()
    # The test harness clears every key source, so it must say so plainly.
    assert status.get_attribute("data-present") == "false"
    assert "Not configured" in status.inner_text()

    body = page.get_by_test_id("settings").inner_text()
    assert "AIza" not in body
    assert "AQ." not in body


def test_back_up_now_writes_a_backup(page, app) -> None:
    """Spec §17 — the manual button."""
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        subject = c.post("/api/subjects", json={"name": "GenAI"}).json()
        assert subject["id"]

    _open_settings(page)
    assert page.get_by_test_id("backup-list").count() == 0

    page.get_by_test_id("backup-now").click()
    page.get_by_test_id("backup-list").wait_for(state="visible", timeout=15_000)

    rows = page.get_by_test_id("backup-list").inner_text()
    assert "revisenlearn-" in rows

    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        listing = c.get("/api/backup/list").json()
    assert len(listing["backups"]) == 1

    # The copy really is a database with the data in it.
    path = Path(listing["backups"][0]["path"])
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        assert conn.execute("SELECT name FROM subjects").fetchall() == [("GenAI",)]
    finally:
        conn.close()


def test_export_writes_markdown_and_reports_where(page, app) -> None:
    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        subject = c.post("/api/subjects", json={"name": "GenAI"}).json()
        topic = c.post(
            "/api/topics", json={"subject_id": subject["id"], "name": "Retrieval"}
        ).json()
        subtopic = c.post(
            "/api/subtopics", json={"topic_id": topic["id"], "name": "Hybrid search"}
        ).json()
        note = c.post("/api/notes/ensure", json={"subtopic_id": subtopic["id"]}).json()
        c.put(
            f"/api/notes/{note['id']}/blocks",
            json={"blocks": [{"id": None, "position": 0,
                              "block_type": "bullet_list_item",
                              "text": "RRF merges the two rankings"}]},
        )

    _open_settings(page)
    page.get_by_test_id("export-markdown").click()

    result = page.get_by_test_id("export-result")
    result.wait_for(state="visible", timeout=20_000)
    text = result.inner_text()
    assert "1 note" in text

    # Follow the reported path and read the file as plain text.
    exported = Path(text.split("→")[-1].strip())
    assert exported.is_dir()
    md = exported / "GenAI" / "Retrieval" / "Hybrid search"
    files = list(md.glob("*.md"))
    assert len(files) == 1
    assert "RRF merges the two rankings" in files[0].read_text()


def test_settings_shows_the_controls_that_actually_do_something(page) -> None:
    """Consolidated addendum §8 — those four groups were listed as "Still to
    come" while three of them were already wired up. They are controls now,
    and the one that genuinely is not editable (model assignment, a config
    change per spec §12.2) says so rather than being hidden."""
    _open_settings(page)
    body = page.get_by_test_id("settings").inner_text()

    for testid in ["threshold-auto", "fsrs-retention", "session-practice"]:
        page.get_by_test_id(testid).wait_for(state="visible")
    # Model assignment is a config change (§12.2), so it is shown, not edited.
    page.get_by_test_id("model-assignments").wait_for(state="visible")
    assert "config/providers.yaml" in body
    assert "Still to come" not in body


def test_settings_does_not_scroll_sideways_when_narrow(page) -> None:
    """Spec §14.1 — the backup list holds long filenames and absolute paths,
    which is exactly what blows out a 500px layout."""
    _open_settings(page)
    page.get_by_test_id("backup-now").click()
    page.get_by_test_id("backup-list").wait_for(state="visible", timeout=15_000)

    page.set_viewport_size({"width": 500, "height": 900})
    page.wait_for_timeout(250)

    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"page scrolls horizontally by {overflow}px at 500px"
