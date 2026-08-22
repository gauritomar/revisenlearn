"""The concepts and merge-queue API (spec §15, §13.2).

Drives the running server, then reads the database to confirm what happened.
"""

from __future__ import annotations


HYBRID = {
    "name": "Hybrid search",
    "definition": ("Combining BM25 lexical scoring with dense vector retrieval "
                   "and fusing the rankings."),
}
HYBRID_NEAR = {
    "name": "Hybrid retrieval",
    "definition": ("Combining BM25 lexical scoring with dense vector retrieval "
                   "and fusing the rankings."),
}
RRF_LONG = {
    "name": "Reciprocal rank fusion",
    "definition": "A method to merge two ranked lists by summing reciprocal ranks.",
}
RRF_SHORT = {
    "name": "RRF",
    "definition": "Merging ranked lists by summing the reciprocal of each document rank.",
}


def _subject(client, name="GenAI") -> int:
    return client.post("/api/subjects", json={"name": name}).json()["id"]


def test_creating_a_concept_reports_it_as_new(app, client) -> None:
    subject = _subject(client)
    body = client.post("/api/concepts",
                       json={**HYBRID, "subject_id": subject}).json()

    assert body["action"] == "new"
    assert body["concept"]["canonical_name"] == "Hybrid search"
    assert body["concept"]["normalised_name"] == "hybrid search"
    assert body["concept"]["status"] == "active"
    assert app.query("SELECT count(*) FROM concepts")[0][0] == 1
    # An embedding was stored alongside it.
    assert app.query(
        "SELECT target_type, dim FROM embeddings"
    ) == [("concept", 384)]


def test_a_near_duplicate_auto_merges_through_the_api(app, client) -> None:
    """Phase 4's done-when, over HTTP."""
    subject = _subject(client)
    first = client.post("/api/concepts",
                        json={**HYBRID, "subject_id": subject}).json()

    second = client.post("/api/concepts",
                         json={**HYBRID_NEAR, "subject_id": subject}).json()

    assert second["action"] == "auto_merge"
    assert second["similarity"] >= 0.92
    assert second["concept"]["id"] == first["concept"]["id"]

    # Only one concept is live; the other is archived, not gone.
    live = client.get("/api/concepts").json()
    assert len(live) == 1
    assert app.query("SELECT count(*) FROM concepts")[0][0] == 2
    assert app.query(
        "SELECT decided_by FROM concept_merges"
    ) == [("auto",)]


def test_the_merge_queue_holds_middling_matches(app, client) -> None:
    subject = _subject(client)
    client.post("/api/concepts", json={**RRF_LONG, "subject_id": subject})
    client.post("/api/concepts", json={**RRF_SHORT, "subject_id": subject})

    queue = client.get("/api/graph/merge-queue").json()

    assert len(queue) == 1
    assert queue[0]["decided_by"] is None
    assert 0.82 <= queue[0]["similarity"] < 0.92
    assert queue[0]["merged_from_name"] == "RRF"
    assert queue[0]["merged_into_name"] == "Reciprocal rank fusion"
    # Both concepts are still live while the decision is pending.
    assert len(client.get("/api/concepts").json()) == 2


def test_accepting_a_queued_merge(app, client) -> None:
    subject = _subject(client)
    client.post("/api/concepts", json={**RRF_LONG, "subject_id": subject})
    client.post("/api/concepts", json={**RRF_SHORT, "subject_id": subject})
    queued = client.get("/api/graph/merge-queue").json()[0]

    client.post("/api/graph/merge",
                json={"merged_from_id": queued["merged_from_id"],
                      "merged_into_id": queued["merged_into_id"]})

    assert client.get("/api/graph/merge-queue").json() == []
    assert len(client.get("/api/concepts").json()) == 1
    decided = app.query("SELECT decided_by FROM concept_merges")
    assert decided == [("user",)]


def test_rejecting_a_queued_merge_keeps_both(app, client) -> None:
    subject = _subject(client)
    client.post("/api/concepts", json={**RRF_LONG, "subject_id": subject})
    client.post("/api/concepts", json={**RRF_SHORT, "subject_id": subject})
    queued = client.get("/api/graph/merge-queue").json()[0]

    client.post(f"/api/graph/merge/{queued['id']}/reject")

    assert client.get("/api/graph/merge-queue").json() == []
    assert len(client.get("/api/concepts").json()) == 2


def test_a_merge_can_be_reverted_through_the_api(app, client) -> None:
    subject = _subject(client)
    client.post("/api/concepts", json={**HYBRID, "subject_id": subject})
    client.post("/api/concepts", json={**HYBRID_NEAR, "subject_id": subject})

    merges = client.get("/api/graph/merges").json()
    assert len(merges) == 1

    restored = client.post(f"/api/graph/merge/{merges[0]['id']}/revert").json()

    assert restored["status"] == "active"
    assert len(client.get("/api/concepts").json()) == 2
    assert app.query(
        "SELECT reverted_at IS NOT NULL FROM concept_merges"
    ) == [(1,)]


def test_reverting_twice_is_refused(app, client) -> None:
    subject = _subject(client)
    client.post("/api/concepts", json={**HYBRID, "subject_id": subject})
    client.post("/api/concepts", json={**HYBRID_NEAR, "subject_id": subject})
    merge_id = client.get("/api/graph/merges").json()[0]["id"]

    assert client.post(f"/api/graph/merge/{merge_id}/revert").status_code == 200
    assert client.post(f"/api/graph/merge/{merge_id}/revert").status_code == 409


def test_similarity_can_be_previewed_before_merging(app, client) -> None:
    subject = _subject(client)
    client.post("/api/concepts", json={**HYBRID, "subject_id": subject})

    body = client.get("/api/concepts/similar",
                      params={**HYBRID_NEAR, "subject_id": subject}).json()

    assert body["concept"]["canonical_name"] == "Hybrid search"
    assert body["similarity"] >= 0.92
    assert body["thresholds"] == {"auto_merge": 0.92, "merge_queue": 0.82}


def test_resolve_false_forces_a_new_concept(app, client) -> None:
    """The graph console adding something it knows is distinct."""
    subject = _subject(client)
    client.post("/api/concepts", json={**HYBRID, "subject_id": subject})

    body = client.post(
        "/api/concepts",
        json={**HYBRID_NEAR, "subject_id": subject, "resolve": False},
    ).json()

    assert body["action"] == "new"
    assert len(client.get("/api/concepts").json()) == 2


def test_renaming_a_concept_re_embeds_it(app, client) -> None:
    subject = _subject(client)
    created = client.post("/api/concepts",
                          json={**HYBRID, "subject_id": subject}).json()
    before = app.query("SELECT vector FROM embeddings")[0][0]

    client.patch(f"/api/concepts/{created['concept']['id']}",
                 json={"canonical_name": "Sparse-dense fusion",
                       "definition": "Something entirely different about trees."})

    after = app.query("SELECT vector FROM embeddings")[0][0]
    assert after != before
    assert app.query("SELECT normalised_name FROM concepts") == [
        ("sparse dense fusion",)
    ]


def test_aliases_can_be_added_by_hand(app, client) -> None:
    subject = _subject(client)
    created = client.post("/api/concepts",
                          json={**RRF_LONG, "subject_id": subject}).json()

    body = client.post(f"/api/concepts/{created['concept']['id']}/aliases",
                       json={"alias": "RRF"}).json()

    assert "RRF" in body["aliases"]
    # And that alias now resolves as an exact match.
    again = client.post("/api/concepts",
                        json={"name": "rrf", "definition": "…",
                              "subject_id": subject}).json()
    assert again["action"] == "exact"
    assert again["concept"]["id"] == created["concept"]["id"]


def test_deleting_a_stale_concept_follows_7_4(app, client) -> None:
    """Spec §7.4 — soft-delete the concept, hard-delete its MCQs, suspend its
    review items."""
    import sqlite3

    subject = _subject(client)
    created = client.post("/api/concepts",
                          json={**HYBRID, "subject_id": subject}).json()
    concept_id = created["concept"]["id"]

    conn = sqlite3.connect(app.db_path)
    conn.execute(
        "INSERT INTO mcqs (concept_id, dimension, stem, options_json, "
        "correct_option_id, status, times_served, times_correct, "
        "consecutive_correct, created_at) "
        "VALUES (?, 'recall', '?', '[]', 'a', 'active', 0, 0, 0, '2026-01-01')",
        (concept_id,),
    )
    conn.execute(
        "INSERT INTO review_items (concept_id, dimension, lapses, reps, "
        "suspended, created_at, updated_at) "
        "VALUES (?, 'explain', 0, 3, 0, '2026-01-01', '2026-01-01')",
        (concept_id,),
    )
    conn.commit()
    conn.close()

    assert client.delete(f"/api/concepts/{concept_id}").status_code == 204

    # Concept soft-deleted, MCQs gone, review item suspended.
    assert app.query("SELECT count(*) FROM concepts")[0][0] == 1
    assert app.query("SELECT status, deleted_at IS NOT NULL FROM concepts") == [
        ("archived", 1)
    ]
    assert app.query("SELECT count(*) FROM mcqs")[0][0] == 0
    assert app.query("SELECT suspended, reps FROM review_items") == [(1, 3)]


def test_editing_a_note_block_makes_its_concept_stale(app, client) -> None:
    """Spec §7.4, end to end through the note-saving path."""
    import sqlite3

    subject = _subject(client)
    topic = client.post("/api/topics",
                        json={"subject_id": subject, "name": "Retrieval"}).json()
    subtopic = client.post("/api/subtopics",
                           json={"topic_id": topic["id"],
                                 "name": "Hybrid search"}).json()
    note = client.post("/api/notes/ensure",
                       json={"subtopic_id": subtopic["id"]}).json()
    saved = client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [{"id": None, "position": 0,
                          "block_type": "bullet_list_item",
                          "text": "BM25 plus dense, fused"}]},
    ).json()
    block_id = saved["blocks"][0]["id"]

    concept = client.post("/api/concepts",
                          json={**HYBRID, "subject_id": subject}).json()
    conn = sqlite3.connect(app.db_path)
    conn.execute(
        "INSERT INTO concept_sources (concept_id, note_block_id, note_id, "
        "created_at) VALUES (?, ?, ?, '2026-01-01')",
        (concept["concept"]["id"], block_id, note["id"]),
    )
    conn.commit()
    conn.close()

    assert client.get(f"/api/concepts/{concept['concept']['id']}").json()["status"] == "active"

    # Edit the block the concept came from.
    client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [{"id": block_id, "position": 0,
                          "block_type": "bullet_list_item",
                          "text": "Completely rewritten now"}]},
    )

    after = client.get(f"/api/concepts/{concept['concept']['id']}").json()
    assert after["status"] == "stale"
    assert after["source_count"] == 0
    assert [c["id"] for c in client.get("/api/graph/stale").json()] == [
        concept["concept"]["id"]
    ]
