"""The notes-first rework (consolidated addendum §2, §3, §4, §7, §8).

The addendum's own framing: "Notes are the centre of the app. Everything else —
checklists, resources, concepts — is derived from what the user writes." These
tests hold that line from the outside: nothing here creates a checklist item, a
resource or a divider by hand. Each one is a side effect of writing a note.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlmodel import select

from revisenlearn.models import ChecklistItem, Note, NoteBlock, Resource


# --------------------------------------------------------------------------
# Helpers — the tree, and a note in it
# --------------------------------------------------------------------------

def _tree(client) -> dict:
    subject = client.post("/api/subjects", json={"name": "GenAI"}).json()
    topic = client.post("/api/topics", json={"subject_id": subject["id"],
                                             "name": "Retrieval"}).json()
    subtopic = client.post("/api/subtopics", json={"topic_id": topic["id"],
                                                   "name": "Chunking"}).json()
    lesson = client.post("/api/lessons",
                         json={"topic_id": topic["id"],
                               "subtopic_id": subtopic["id"],
                               "name": "Fixed vs semantic chunking"}).json()
    return {"subject": subject, "topic": topic,
            "subtopic": subtopic, "lesson": lesson}


def _write(client, note_id: int, lines: list[str]) -> None:
    client.put(
        f"/api/notes/{note_id}/blocks",
        json={"blocks": [
            {"id": None, "position": i, "block_type": "paragraph", "text": text}
            for i, text in enumerate(lines)
        ]},
    )


# --------------------------------------------------------------------------
# §2 — checklist items are a projection of note blocks
# --------------------------------------------------------------------------

def test_typing_a_checkbox_creates_a_checklist_item(client) -> None:
    """Typing `- [ ] text` creates one; `- [x] text` creates it pre-checked."

    And the projection stores the *content*, not the syntax — the markers
    belong to the editor, and leaking them would put raw markdown in the
    Todos board.
    """
    tree = _tree(client)
    note = client.post("/api/notes/ensure",
                       json={"lesson_id": tree["lesson"]["id"]}).json()
    _write(client, note["id"], ["- [ ] Read the chunking paper",
                                "- [x] Skim the docs",
                                "Not a checklist line"])

    items = client.get(f"/api/notes/{note['id']}/checklist").json()
    assert [(i["text"], i["checked"]) for i in items] == [
        ("Read the chunking paper", False),
        ("Skim the docs", True),
    ]

    # The blocks themselves were retyped, so the editor reopens with boxes.
    blocks = client.get(f"/api/notes/{note['id']}").json()["blocks"]
    assert [b["block_type"] for b in blocks[:2]] == ["checklist_item"] * 2


def test_toggling_from_outside_writes_through_to_the_block(client) -> None:
    """Addendum §2 **[LOCKED]**: "that write goes through to the underlying
    `note_blocks` row — never a separate, divergent copy of the state."""
    tree = _tree(client)
    note = client.post("/api/notes/ensure",
                       json={"lesson_id": tree["lesson"]["id"]}).json()
    _write(client, note["id"], ["- [ ] Read the chunking paper"])
    item = client.get(f"/api/notes/{note['id']}/checklist").json()[0]

    client.patch(f"/api/checklist/{item['id']}", json={"checked": True})

    blocks = client.get(f"/api/notes/{note['id']}").json()["blocks"]
    assert blocks[0]["checked"] is True
    assert blocks[0]["text"] == "- [x] Read the chunking paper"
    # …and the projection agrees, because it was re-derived from that block.
    again = client.get(f"/api/notes/{note['id']}/checklist").json()[0]
    assert again["checked"] is True


def test_deleting_the_line_deletes_the_item(client) -> None:
    """A projection keeps nothing of its own: no orphan survives the block."""
    tree = _tree(client)
    note = client.post("/api/notes/ensure",
                       json={"lesson_id": tree["lesson"]["id"]}).json()
    _write(client, note["id"], ["- [ ] Temporary", "- [ ] Keep me"])
    assert len(client.get(f"/api/notes/{note['id']}/checklist").json()) == 2

    _write(client, note["id"], ["- [ ] Keep me"])
    items = client.get(f"/api/notes/{note['id']}/checklist").json()
    assert [i["text"] for i in items] == ["Keep me"]


def test_turning_a_checkbox_back_into_prose_drops_the_item(client) -> None:
    tree = _tree(client)
    note = client.post("/api/notes/ensure",
                       json={"lesson_id": tree["lesson"]["id"]}).json()
    _write(client, note["id"], ["- [ ] Read the paper"])
    assert client.get(f"/api/notes/{note['id']}/checklist").json()

    _write(client, note["id"], ["Read the paper"])
    assert client.get(f"/api/notes/{note['id']}/checklist").json() == []


def test_there_is_no_way_to_create_a_checklist_item_directly(client) -> None:
    """**This table has no dedicated CRUD UI.**" The API has no such route
    either — the only writes are toggles."""
    assert client.post("/api/checklist", json={"text": "smuggled"}).status_code in (404, 405)
    assert client.delete("/api/checklist/1").status_code in (404, 405)


def test_a_lessons_checklist_comes_from_its_note(client) -> None:
    tree = _tree(client)
    note = client.post("/api/notes/ensure",
                       json={"lesson_id": tree["lesson"]["id"]}).json()
    _write(client, note["id"], ["- [ ] One", "- [x] Two"])

    items = client.get(f"/api/lessons/{tree['lesson']['id']}/checklist").json()
    assert [i["text"] for i in items] == ["One", "Two"]

    # And the roadmap rollup counts them: one of two ticked.
    roadmap = client.get("/api/roadmap").json()
    lesson = roadmap["subjects"][0]["topics"][0]["subtopics"][0]["lessons"][0]
    assert lesson["pct"] == 50.0


# --------------------------------------------------------------------------
# §3 — one continuous note per lesson
# --------------------------------------------------------------------------

def test_a_lesson_has_one_continuous_note_across_days(client) -> None:
    """Addendum §3 **[LOCKED]**: "A Lesson has ONE note that grows over time …
    not a new note per day." So `ensure` on a later day must return the same
    note, which means it deliberately does not filter on `study_date`.
    """
    tree = _tree(client)
    first = client.post("/api/notes/ensure",
                        json={"lesson_id": tree["lesson"]["id"]}).json()
    _write(client, first["id"], ["Fixed-size chunking is a baseline"])

    later = client.post(
        "/api/notes/ensure",
        json={"lesson_id": tree["lesson"]["id"],
              "study_date": (dt.date.today() + dt.timedelta(days=9)).isoformat()},
    ).json()

    assert later["id"] == first["id"]
    assert [b["text"] for b in later["blocks"]][0] == "Fixed-size chunking is a baseline"


def test_a_new_day_on_an_existing_note_adds_one_date_divider(session) -> None:
    """insert a lightweight date-divider block automatically, so a note
    spanning months stays navigable" — once per day, and never on an empty
    note. Driven in-process because it turns on `updated_at` being yesterday.
    """
    from revisenlearn.api.notes import _maybe_add_date_divider

    note = Note(title="Chunking", study_date=dt.date.today())
    session.add(note)
    session.flush()
    from revisenlearn.hashing import content_hash

    text = "Yesterday's thinking"
    session.add(NoteBlock(note_id=note.id, position=0, block_type="paragraph",
                          text=text, content_hash=content_hash(text)))
    note.updated_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    session.flush()

    _maybe_add_date_divider(session, note)
    _maybe_add_date_divider(session, note)   # idempotent

    dividers = session.exec(
        select(NoteBlock).where(NoteBlock.note_id == note.id,
                                NoteBlock.block_type == "date_divider")
    ).all()
    assert [d.text for d in dividers] == [dt.date.today().isoformat()]


def test_no_divider_is_added_to_an_empty_note(session) -> None:
    from revisenlearn.api.notes import _maybe_add_date_divider

    note = Note(title="Empty", study_date=dt.date.today())
    note.updated_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
    session.add(note)
    session.flush()

    _maybe_add_date_divider(session, note)

    assert session.exec(
        select(NoteBlock).where(NoteBlock.note_id == note.id)
    ).all() == []


def test_a_lesson_note_inherits_the_lessons_placement(client) -> None:
    tree = _tree(client)
    note = client.post("/api/notes/ensure",
                       json={"lesson_id": tree["lesson"]["id"]}).json()
    assert note["subtopic_id"] == tree["subtopic"]["id"]
    assert note["topic_id"] == tree["topic"]["id"]
    assert note["subject_id"] == tree["subject"]["id"]


# --------------------------------------------------------------------------
# §4 — resources are auto-detected from URLs in notes
# --------------------------------------------------------------------------

def test_a_url_in_a_note_becomes_a_resource(client) -> None:
    """Addendum §4: a link typed into a note is "a second path into the *same*
    table", inheriting the note's placement and the usual type inference."""
    tree = _tree(client)
    note = client.post("/api/notes/ensure",
                       json={"lesson_id": tree["lesson"]["id"]}).json()
    _write(client, note["id"],
           ["Good explainer: https://www.youtube.com/watch?v=chunk101"])

    resources = client.get("/api/resources").json()
    assert len(resources) == 1
    found = resources[0]
    assert found["url"] == "https://youtube.com/watch?v=chunk101"
    assert found["resource_type"] == "youtube_video"
    assert found["status"] == "inbox"
    assert found["subject_id"] == tree["subject"]["id"]
    assert found["subtopic_id"] == tree["subtopic"]["id"]


def test_the_same_link_written_twice_is_one_resource(client) -> None:
    """Normalisation is deliberately conservative — host case, `www.` and a
    trailing slash only — but enough that rewriting a line doesn't fork the
    resource."""
    tree = _tree(client)
    note = client.post("/api/notes/ensure",
                       json={"lesson_id": tree["lesson"]["id"]}).json()
    _write(client, note["id"], ["https://Example.com/chunking/"])
    _write(client, note["id"], ["https://Example.com/chunking/",
                                "again: https://www.example.com/chunking"])

    resources = client.get("/api/resources").json()
    assert len(resources) == 1


def test_a_link_that_cannot_be_reached_still_saves_the_note(client) -> None:
    """Principle §1.2 **[LOCKED]** — note-taking never blocks. A dead host
    costs a title, not a save."""
    tree = _tree(client)
    note = client.post("/api/notes/ensure",
                       json={"lesson_id": tree["lesson"]["id"]}).json()
    response = client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [{"id": None, "position": 0, "block_type": "paragraph",
                          "text": "http://127.0.0.1:9/nothing-here"}]},
    )
    assert response.status_code == 200
    assert client.get(f"/api/notes/{note['id']}").json()["blocks"][0]["text"]


def test_a_manually_added_resource_is_indistinguishable(client) -> None:
    """a resource doesn't 'know' which way it was added" — so writing the URL
    of a hand-added resource attaches to that row rather than making a twin."""
    manual = client.post("/api/resources",
                         json={"url": "https://example.com/deep-dive",
                               "title": "Deep dive"}).json()
    tree = _tree(client)
    note = client.post("/api/notes/ensure",
                       json={"lesson_id": tree["lesson"]["id"]}).json()
    _write(client, note["id"], ["see https://example.com/deep-dive"])

    resources = client.get("/api/resources").json()
    assert [r["id"] for r in resources] == [manual["id"]]
    assert resources[0]["title"] == "Deep dive"     # not overwritten


# --------------------------------------------------------------------------
# §7 — the pipeline preview, shown before the money is spent
# --------------------------------------------------------------------------

def test_pending_preview_lists_the_blocks_that_would_be_sent(client) -> None:
    """This is the moment the user is about to spend real money; they should
    see what's paying for it."""
    tree = _tree(client)
    note = client.post("/api/notes/ensure",
                       json={"lesson_id": tree["lesson"]["id"]}).json()
    _write(client, note["id"], ["Fixed-size chunking splits on a token budget",
                                "Semantic chunking splits on meaning"])

    preview = client.get("/api/pipeline/pending", params={"preview": True}).json()

    assert preview["unprocessed_blocks"] == 2
    assert [b["snippet"] for b in preview["blocks"]] == [
        "Fixed-size chunking splits on a token budget",
        "Semantic chunking splits on meaning",
    ]
    assert {b["state"] for b in preview["blocks"]} == {"unprocessed"}
    assert all(b["note_title"] == note["title"] for b in preview["blocks"])
    assert preview["estimated_tokens"] > 0


def test_the_plain_pending_count_stays_cheap(client) -> None:
    """The badge polls this; it must not drag every block's text with it."""
    tree = _tree(client)
    note = client.post("/api/notes/ensure",
                       json={"lesson_id": tree["lesson"]["id"]}).json()
    _write(client, note["id"], ["Something worth processing"])

    body = client.get("/api/pipeline/pending").json()
    assert body["unprocessed_blocks"] == 1
    assert body["blocks"] == []


def test_a_long_block_is_truncated_in_the_preview(client) -> None:
    tree = _tree(client)
    note = client.post("/api/notes/ensure",
                       json={"lesson_id": tree["lesson"]["id"]}).json()
    _write(client, note["id"], ["word " * 200])

    block = client.get("/api/pipeline/pending",
                       params={"preview": True}).json()["blocks"][0]
    assert len(block["snippet"]) <= 161 and block["snippet"].endswith("…")


# --------------------------------------------------------------------------
# §8 — Settings actually drive behaviour
# --------------------------------------------------------------------------

def test_session_defaults_are_read_not_just_stored(client) -> None:
    """Addendum §8: "`settings.session_defaults` was seeded but never read."
    It is read now, so changing it changes what a session offers."""
    seeded = client.get("/api/practice/defaults").json()
    assert seeded["default"] == 20
    assert seeded["options"] == [20, 30, 50]
    assert client.get("/api/revision/dashboard").json()["default_size"] == 5

    client.patch("/api/settings", json={"values": {
        "session_defaults": {"practice_count": 8, "revision_count": 3}}})

    changed = client.get("/api/practice/defaults").json()
    assert changed["default"] == 8
    # The picker still offers the spec's three, with the setting added.
    assert changed["options"] == [8, 20, 30, 50]
    assert client.get("/api/revision/dashboard").json()["default_size"] == 3


def test_the_model_assignment_is_shown_but_not_editable(client) -> None:
    """Spec §12.2 keeps model choice a config change, so Settings shows it
    read-only — and no key material crosses the boundary."""
    body = client.get("/api/providers").json()
    assert body["source"] == "config/providers.yaml"
    assert body["tasks"]
    assert "key" not in str(body).lower() or "api_key" not in body
