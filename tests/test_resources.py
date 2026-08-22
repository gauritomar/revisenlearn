"""Resources — the study to-do and the anchor for notes (spec §5).

§5.1 is the requirement that shapes all of this: adding a resource must take
under five seconds. These tests hold that line — one field in, sensible
defaults out.
"""

from __future__ import annotations

import datetime as dt
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

TODAY = dt.date.today().isoformat()


# --------------------------------------------------------------------------
# A real local HTTP server, so the title fetch is exercised for real rather
# than mocked. Nothing here touches the public internet.
# --------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, str, bytes]] = {}

    def do_GET(self):  # noqa: N802
        status, content_type, body = self.routes.get(
            self.path, (404, "text/plain", b"nope")
        )
        if self.path == "/slow":
            import time
            time.sleep(5)  # longer than the 3s budget
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


@pytest.fixture(scope="module")
def web():
    _Handler.routes = {
        "/good": (200, "text/html; charset=utf-8",
                  b"<html><head><title>  Attention Is All\nYou Need </title></head></html>"),
        "/entities": (200, "text/html",
                      b"<html><head><title>Q&amp;A &lt;deep&gt; dive</title></head></html>"),
        "/notitle": (200, "text/html", b"<html><head></head><body>hi</body></html>"),
        "/pdf": (200, "application/pdf", b"%PDF-1.4 not html"),
        "/boom": (500, "text/html", b"<html><title>Error</title></html>"),
        "/slow": (200, "text/html", b"<html><title>Too slow</title></html>"),
    }
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


# --------------------------------------------------------------------------
# The fast-add flow (§5.1)
# --------------------------------------------------------------------------

def test_adding_a_resource_needs_only_a_url(app, client) -> None:
    created = client.post("/api/resources", json={"url": "https://example.com/x"}).json()

    assert created["id"]
    # Fail silently to the raw URL — never block the add on a fetch.
    assert created["title"] == "https://example.com/x"
    assert created["status"] == "inbox"
    assert created["progress_pct"] == 0
    assert app.query("SELECT count(*) FROM resources")[0][0] == 1


def test_adding_a_resource_needs_only_a_title(app, client) -> None:
    created = client.post("/api/resources", json={"title": "Read CLRS ch. 4"}).json()
    assert created["title"] == "Read CLRS ch. 4"
    assert created["url"] is None
    assert created["resource_type"] == "other"


def test_a_resource_needs_a_url_or_a_title(client) -> None:
    assert client.post("/api/resources", json={}).status_code == 400


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/watch?v=abc123", "youtube_video"),
        ("https://www.youtube.com/playlist?list=PL123", "youtube_playlist"),
        ("https://arxiv.org/abs/1706.03762", "paper"),
        ("https://example.com/paper.pdf", "pdf"),
        ("https://leetcode.com/problems/two-sum/", "problem_set"),
        ("https://www.coursera.org/learn/ml", "course"),
        ("https://someblog.dev/post", "article"),
        (None, "other"),
    ],
)
def test_resource_type_is_inferred_from_the_url(client, url, expected) -> None:
    """One less thing to pick, so the add stays under five seconds."""
    payload = {"url": url} if url else {"title": "No link"}
    assert client.post("/api/resources", json=payload).json()["resource_type"] == expected


def test_explicit_resource_type_beats_inference(client) -> None:
    created = client.post(
        "/api/resources",
        json={"url": "https://arxiv.org/abs/1706.03762", "resource_type": "book"},
    ).json()
    assert created["resource_type"] == "book"


def test_invalid_status_and_type_are_rejected(client) -> None:
    assert client.post(
        "/api/resources", json={"title": "x", "status": "nonsense"}
    ).status_code == 400
    assert client.post(
        "/api/resources", json={"title": "x", "resource_type": "nonsense"}
    ).status_code == 400


# --------------------------------------------------------------------------
# Title probing (§5.1: one request, 3s timeout, fail silently)
# --------------------------------------------------------------------------

def test_probe_title_reads_the_page_title(client, web) -> None:
    result = client.post(
        "/api/resources/probe-title", json={"url": f"{web}/good"}
    ).json()
    # Whitespace, including the newline, is collapsed.
    assert result["title"] == "Attention Is All You Need"


def test_probe_title_unescapes_entities(client, web) -> None:
    result = client.post(
        "/api/resources/probe-title", json={"url": f"{web}/entities"}
    ).json()
    assert result["title"] == "Q&A <deep> dive"


@pytest.mark.parametrize("path", ["/notitle", "/pdf", "/boom", "/missing"])
def test_probe_title_fails_silently(client, web, path) -> None:
    """Every failure mode is a null title and a 200, never an error the user
    has to deal with mid-add."""
    response = client.post("/api/resources/probe-title", json={"url": f"{web}{path}"})
    assert response.status_code == 200
    assert response.json()["title"] is None


def test_probe_title_rejects_non_http_schemes(client) -> None:
    for url in ["file:///etc/passwd", "ftp://example.com", "javascript:alert(1)"]:
        result = client.post("/api/resources/probe-title", json={"url": url}).json()
        assert result["title"] is None


def test_probe_title_gives_up_after_three_seconds(client, web) -> None:
    """Spec §5.1 — 3s timeout. A slow page must not hold up the add."""
    import time

    start = time.monotonic()
    result = client.post("/api/resources/probe-title", json={"url": f"{web}/slow"})
    elapsed = time.monotonic() - start

    assert result.status_code == 200
    assert result.json()["title"] is None
    assert elapsed < 4.5, f"probe took {elapsed:.1f}s, budget is 3s"


def test_probe_title_still_infers_the_type_when_the_fetch_fails(client) -> None:
    result = client.post(
        "/api/resources/probe-title",
        json={"url": "https://www.youtube.com/watch?v=nope"},
    ).json()
    assert result["resource_type"] == "youtube_video"


# --------------------------------------------------------------------------
# Last-used placement (§5.1)
# --------------------------------------------------------------------------

def _branch(client) -> dict:
    subject = client.post("/api/subjects", json={"name": "GenAI"}).json()
    topic = client.post(
        "/api/topics", json={"subject_id": subject["id"], "name": "Retrieval"}
    ).json()
    subtopic = client.post(
        "/api/subtopics", json={"topic_id": topic["id"], "name": "Hybrid search"}
    ).json()
    return {"subject": subject, "topic": topic, "subtopic": subtopic}


def test_placement_defaults_to_the_last_used_values(app, client) -> None:
    branch = _branch(client)

    first = client.post(
        "/api/resources",
        json={"title": "First", "subtopic_id": branch["subtopic"]["id"]},
    ).json()
    assert first["subtopic_id"] == branch["subtopic"]["id"]
    # Ancestry is filled in from the subtopic.
    assert first["topic_id"] == branch["topic"]["id"]
    assert first["subject_id"] == branch["subject"]["id"]

    # The next add sends no placement at all and inherits it.
    second = client.post("/api/resources", json={"title": "Second"}).json()
    assert second["subtopic_id"] == branch["subtopic"]["id"]
    assert second["subject_id"] == branch["subject"]["id"]

    assert client.get("/api/resources/last-used").json()["subtopic_id"] == \
        branch["subtopic"]["id"]


def test_explicit_placement_beats_the_remembered_one(client) -> None:
    branch = _branch(client)
    other = client.post("/api/subjects", json={"name": "Systems"}).json()

    client.post("/api/resources",
                json={"title": "A", "subtopic_id": branch["subtopic"]["id"]})
    second = client.post(
        "/api/resources", json={"title": "B", "subject_id": other["id"]}
    ).json()

    assert second["subject_id"] == other["id"]
    assert second["subtopic_id"] is None


# --------------------------------------------------------------------------
# Status, progress and the to-do flow (§5)
# --------------------------------------------------------------------------

def test_progress_is_set_by_hand_and_never_computed(app, client) -> None:
    resource = client.post("/api/resources", json={"title": "Long course"}).json()

    updated = client.patch(
        f"/api/resources/{resource['id']}",
        json={"progress_pct": 40, "progress_note": "stopped at chapter 4"},
    ).json()

    assert updated["progress_pct"] == 40
    assert updated["progress_note"] == "stopped at chapter 4"
    assert app.query("SELECT progress_pct, progress_note FROM resources") == [
        (40, "stopped at chapter 4")
    ]


def test_progress_is_clamped_to_0_100(client) -> None:
    resource = client.post("/api/resources", json={"title": "x"}).json()
    for bad in (-1, 101):
        assert client.patch(
            f"/api/resources/{resource['id']}", json={"progress_pct": bad}
        ).status_code == 422


def test_completing_a_resource_stamps_it_and_fills_progress(client) -> None:
    resource = client.post("/api/resources", json={"title": "Nearly done"}).json()
    client.patch(f"/api/resources/{resource['id']}", json={"progress_pct": 80})

    done = client.patch(
        f"/api/resources/{resource['id']}", json={"status": "completed"}
    ).json()

    assert done["status"] == "completed"
    assert done["completed_at"] is not None
    assert done["progress_pct"] == 100

    # Reopening it clears the completion stamp.
    reopened = client.patch(
        f"/api/resources/{resource['id']}", json={"status": "in_progress"}
    ).json()
    assert reopened["completed_at"] is None


def test_study_next_ranks_started_work_first(client) -> None:
    """Spec §14 'Study next (ranked to-do)'."""
    ids = {}
    for title, status, priority in [
        ("inbox low", "inbox", 0),
        ("inbox high", "inbox", 5),
        ("queued next", "next", 0),
        ("half done", "in_progress", 0),
        ("finished", "completed", 9),
        ("shelved", "archived", 9),
    ]:
        ids[title] = client.post(
            "/api/resources",
            json={"title": title, "status": status, "priority": priority},
        ).json()["id"]

    ranked = [r["title"] for r in client.get("/api/resources/study-next").json()]

    assert ranked[0] == "half done"
    assert ranked[1] == "queued next"
    assert ranked[2] == "inbox high"      # priority breaks the inbox tie
    assert ranked[3] == "inbox low"
    # Completed and archived work is not "study next".
    assert "finished" not in ranked
    assert "shelved" not in ranked


def test_study_next_respects_the_limit(client) -> None:
    for i in range(8):
        client.post("/api/resources", json={"title": f"r{i}"})
    assert len(client.get("/api/resources/study-next", params={"limit": 3}).json()) == 3


def test_opening_a_resource_records_it_and_starts_it(app, client) -> None:
    """§5.1 — 'Open link' opens the default browser and marks the resource
    as being worked on."""
    resource = client.post(
        "/api/resources", json={"url": "https://example.com/watch"}
    ).json()
    assert resource["status"] == "inbox"
    assert resource["last_opened_at"] is None

    opened = client.post(f"/api/resources/{resource['id']}/open").json()

    assert opened["last_opened_at"] is not None
    assert opened["status"] == "in_progress"
    assert app.query("SELECT last_opened_at IS NOT NULL FROM resources") == [(1,)]


def test_opening_a_resource_without_a_url_is_a_400(client) -> None:
    resource = client.post("/api/resources", json={"title": "Paper on my desk"}).json()
    assert client.post(f"/api/resources/{resource['id']}/open").status_code == 400


def test_resources_are_soft_deleted(app, client) -> None:
    resource = client.post("/api/resources", json={"title": "Mistake"}).json()
    assert client.delete(f"/api/resources/{resource['id']}").status_code == 204

    assert client.get("/api/resources").json() == []
    assert client.get(f"/api/resources/{resource['id']}").status_code == 404
    # Principle §1.7 — the row survives.
    assert app.query("SELECT count(*) FROM resources")[0][0] == 1


def test_resources_can_be_filtered(client) -> None:
    branch = _branch(client)
    client.post("/api/resources",
                json={"title": "In GenAI", "subject_id": branch["subject"]["id"]})
    other = client.post("/api/subjects", json={"name": "Systems"}).json()
    client.post("/api/resources", json={"title": "In Systems", "subject_id": other["id"]})

    by_subject = client.get(
        "/api/resources", params={"subject_id": branch["subject"]["id"]}
    ).json()
    assert [r["title"] for r in by_subject] == ["In GenAI"]

    by_status = client.get("/api/resources", params={"status": "inbox"}).json()
    assert len(by_status) == 2


# --------------------------------------------------------------------------
# The resource -> note split view (§5.1)
# --------------------------------------------------------------------------

def test_a_resource_gets_todays_note_created_on_the_spot(app, client) -> None:
    branch = _branch(client)
    resource = client.post(
        "/api/resources",
        json={"url": "https://youtube.com/watch?v=x", "title": "RAG from scratch",
              "subtopic_id": branch["subtopic"]["id"]},
    ).json()

    note = client.post(
        "/api/notes/ensure", json={"resource_id": resource["id"]}
    ).json()

    assert note["resource_id"] == resource["id"]
    assert note["study_date"] == TODAY
    # Titled after the resource, and filed where the resource is filed.
    assert note["title"] == "RAG from scratch"
    assert note["subtopic_id"] == branch["subtopic"]["id"]
    assert note["subject_id"] == branch["subject"]["id"]

    # Asking again returns the same note, not a second one.
    again = client.post("/api/notes/ensure", json={"resource_id": resource["id"]}).json()
    assert again["id"] == note["id"]
    assert app.query("SELECT count(*) FROM notes")[0][0] == 1


def test_a_resource_note_is_distinct_from_the_subtopics_own_note(client) -> None:
    """Opening a subtopic and opening a resource filed under it must not
    collide on the same day."""
    branch = _branch(client)
    resource = client.post(
        "/api/resources",
        json={"title": "A video", "subtopic_id": branch["subtopic"]["id"]},
    ).json()

    subtopic_note = client.post(
        "/api/notes/ensure", json={"subtopic_id": branch["subtopic"]["id"]}
    ).json()
    resource_note = client.post(
        "/api/notes/ensure", json={"resource_id": resource["id"]}
    ).json()

    assert subtopic_note["id"] != resource_note["id"]
    assert subtopic_note["resource_id"] is None
    assert resource_note["resource_id"] == resource["id"]

    # And each is stable on re-open.
    assert client.post(
        "/api/notes/ensure", json={"subtopic_id": branch["subtopic"]["id"]}
    ).json()["id"] == subtopic_note["id"]


def test_notes_can_be_listed_by_resource(client) -> None:
    branch = _branch(client)
    resource = client.post(
        "/api/resources",
        json={"title": "Series", "subtopic_id": branch["subtopic"]["id"]},
    ).json()

    today = client.post("/api/notes/ensure", json={"resource_id": resource["id"]}).json()
    yesterday = client.post(
        "/api/notes",
        json={"resource_id": resource["id"],
              "study_date": (dt.date.today() - dt.timedelta(days=1)).isoformat()},
    ).json()

    listed = client.get("/api/notes", params={"resource_id": resource["id"]}).json()
    assert {n["id"] for n in listed} == {today["id"], yesterday["id"]}


def test_ensure_note_requires_some_anchor(client) -> None:
    assert client.post("/api/notes/ensure", json={}).status_code == 400
