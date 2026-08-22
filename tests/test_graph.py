"""The knowledge graph console (spec §13 **[LOCKED]**).

"This is a curation workspace, not a decoration."
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlmodel import select

from revisenlearn import graph
from revisenlearn.models import (
    Concept,
    ConceptEdge,
    ConceptMerge,
    ConceptSource,
    Note,
    NoteBlock,
    Subject,
    Topic,
)


def _subject(session, name="GenAI") -> Subject:
    row = Subject(name=name)
    session.add(row)
    session.flush()
    return row


def _concept(session, subject, name, *, importance=3.0, difficulty=3.0,
             status="active") -> Concept:
    concept = Concept(canonical_name=name, normalised_name=name.lower(),
                      definition=f"{name} definition.", subject_id=subject.id,
                      importance=importance, difficulty=difficulty,
                      status=status)
    session.add(concept)
    session.flush()
    return concept


def _edge(session, a, b, relation="related_to", status="accepted",
          job_id=None) -> ConceptEdge:
    edge = ConceptEdge(source_concept_id=a.id, target_concept_id=b.id,
                       relation_type=relation, status=status, job_id=job_id,
                       confidence=0.8)
    session.add(edge)
    session.flush()
    return edge


# --------------------------------------------------------------------------
# §13.1 The graph
# --------------------------------------------------------------------------

def test_nodes_carry_badge_and_importance_for_styling(session) -> None:
    """"Nodes coloured by mastery badge state, sized by importance." The server
    supplies both so the client draws rather than decides."""
    subject = _subject(session)
    _concept(session, subject, "Hybrid search", importance=5.0)

    payload = graph.build_graph(session)

    node = payload["nodes"][0]
    assert node["name"] == "Hybrid search"
    assert node["importance"] == 5.0
    assert node["badge"] == "untested"     # never reviewed
    assert node["subject"] == "GenAI"


def test_edges_carry_relation_and_status_for_styling(session) -> None:
    """"Edges styled by `relation_type`, dashed when `status='proposed'`.\""""
    subject = _subject(session)
    a = _concept(session, subject, "A")
    b = _concept(session, subject, "B")
    _edge(session, a, b, "prerequisite_of", status="proposed")

    payload = graph.build_graph(session)

    edge = payload["edges"][0]
    assert edge["relation_type"] == "prerequisite_of"
    assert edge["status"] == "proposed"


def test_rejected_edges_are_not_drawn(session) -> None:
    subject = _subject(session)
    a = _concept(session, subject, "A")
    b = _concept(session, subject, "B")
    _edge(session, a, b, status="rejected")

    assert graph.build_graph(session)["edges"] == []


def test_the_graph_can_be_filtered_by_subject_and_search(session) -> None:
    genai = _subject(session, "GenAI")
    systems = _subject(session, "Systems")
    _concept(session, genai, "Hybrid search")
    _concept(session, systems, "B-trees")

    by_subject = graph.build_graph(session, subject_id=genai.id)
    assert [n["name"] for n in by_subject["nodes"]] == ["Hybrid search"]

    by_search = graph.build_graph(session, search="tree")
    assert [n["name"] for n in by_search["nodes"]] == ["B-trees"]


def test_the_neighbourhood_view_is_two_hops(session) -> None:
    """Spec §13.1 saved view — "Concept neighbourhood (2 hops)"."""
    subject = _subject(session)
    a = _concept(session, subject, "A")
    b = _concept(session, subject, "B")
    c = _concept(session, subject, "C")
    d = _concept(session, subject, "D")      # three hops away
    _edge(session, a, b)
    _edge(session, b, c)
    _edge(session, c, d)

    payload = graph.build_graph(session, view="neighbourhood", concept_id=a.id)

    names = {n["name"] for n in payload["nodes"]}
    assert names == {"A", "B", "C"}
    assert "D" not in names


def test_the_orphan_view_finds_unconnected_concepts(session) -> None:
    subject = _subject(session)
    a = _concept(session, subject, "Connected A")
    b = _concept(session, subject, "Connected B")
    _concept(session, subject, "All alone")
    _edge(session, a, b)

    payload = graph.build_graph(session, view="orphans")
    assert [n["name"] for n in payload["nodes"]] == ["All alone"]


def test_the_stale_view_finds_stale_concepts(session) -> None:
    subject = _subject(session)
    _concept(session, subject, "Fine")
    _concept(session, subject, "No sources left", status="stale")

    payload = graph.build_graph(session, view="stale_concepts")
    assert [n["name"] for n in payload["nodes"]] == ["No sources left"]


def test_the_job_filter_dims_rather_than_removes(session) -> None:
    """Spec §13.4 — "Selecting one dims everything the job did not touch".

    Dimming rather than filtering keeps the surrounding structure visible,
    which is the point of reviewing a run in context.
    """
    from revisenlearn.models import PipelineJob

    subject = _subject(session)
    job = PipelineJob(name="amber-lynx · 22 Aug", status="succeeded")
    session.add(job)
    session.flush()

    touched = _concept(session, subject, "From this run")
    touched.created_by_job_id = job.id
    session.add(touched)
    _concept(session, subject, "From an earlier run")
    session.flush()

    payload = graph.build_graph(session, job_id=job.id)

    # Both are still drawn.
    assert len(payload["nodes"]) == 2
    by_name = {n["name"]: n for n in payload["nodes"]}
    assert by_name["From this run"]["dimmed"] is False
    assert by_name["From an earlier run"]["dimmed"] is True


# --------------------------------------------------------------------------
# §13.2 Work queue
# --------------------------------------------------------------------------

def test_queue_counts_cover_all_five_tabs(session) -> None:
    subject = _subject(session)
    a = _concept(session, subject, "A")
    b = _concept(session, subject, "B")
    _concept(session, subject, "Stale one", status="stale")
    _concept(session, subject, "Orphan")
    _edge(session, a, b, status="proposed")
    session.add(ConceptMerge(merged_from_id=a.id, merged_into_id=b.id,
                             similarity=0.87, decided_by=None))
    session.add(ConceptMerge(merged_from_id=a.id, merged_into_id=b.id,
                             similarity=0.95, decided_by="auto"))
    session.flush()

    counts = graph.queue_counts(session)

    assert counts["merge_queue"] == 1
    assert counts["proposed_edges"] == 1
    assert counts["stale_concepts"] == 1
    assert counts["auto_merged"] == 1
    assert counts["orphans"] >= 1


def test_proposed_edges_flag_cycle_conflicts_with_the_path(session) -> None:
    """Spec §13.2 tab 2 — "Cycle conflicts highlighted with the offending path
    drawn on the graph"."""
    subject = _subject(session)
    a = _concept(session, subject, "A")
    b = _concept(session, subject, "B")
    c = _concept(session, subject, "C")
    _edge(session, a, b, "prerequisite_of", status="accepted")
    _edge(session, b, c, "prerequisite_of", status="accepted")
    # C -> A would close the loop.
    _edge(session, c, a, "prerequisite_of", status="proposed")

    rows = graph.proposed_edges(session)

    assert len(rows) == 1
    assert rows[0]["cycle_conflict"] is True
    # The path runs from the target back to the source.
    assert rows[0]["cycle_path"][0] == a.id
    assert rows[0]["cycle_path"][-1] == c.id


def test_a_harmless_proposed_edge_is_not_flagged(session) -> None:
    subject = _subject(session)
    a = _concept(session, subject, "A")
    b = _concept(session, subject, "B")
    _edge(session, a, b, "prerequisite_of", status="proposed")

    rows = graph.proposed_edges(session)
    assert rows[0]["cycle_conflict"] is False
    assert rows[0]["cycle_path"] == []


def test_auto_merged_shows_only_the_last_thirty_days(session) -> None:
    """Spec §13.2 tab 4 — "a log of `decided_by='auto'` merges from the last 30
    days … This is how the user builds trust in the thresholds.\""""
    subject = _subject(session)
    a = _concept(session, subject, "A")
    b = _concept(session, subject, "B")

    now = dt.datetime.now(dt.timezone.utc)
    session.add(ConceptMerge(merged_from_id=a.id, merged_into_id=b.id,
                             similarity=0.95, decided_by="auto",
                             created_at=now - dt.timedelta(days=3)))
    session.add(ConceptMerge(merged_from_id=a.id, merged_into_id=b.id,
                             similarity=0.93, decided_by="auto",
                             created_at=now - dt.timedelta(days=45)))
    session.flush()

    rows = graph.auto_merged(session)
    assert len(rows) == 1
    assert rows[0]["similarity"] == 0.95


def test_missing_prerequisites_only_flags_harder_concepts(session) -> None:
    subject = _subject(session)
    _concept(session, subject, "Hard and unlinked", difficulty=5.0)
    _concept(session, subject, "Easy and unlinked", difficulty=1.0)

    names = {r["name"] for r in graph.missing_prerequisites(session)}
    assert names == {"Hard and unlinked"}


# --------------------------------------------------------------------------
# §13.3 Direct editing
# --------------------------------------------------------------------------

def test_concept_detail_carries_everything_the_inspector_needs(session) -> None:
    """Spec §13.3 — "view source notes, view review history, view token
    cost"."""
    from revisenlearn.models import LLMRun, ReviewItem

    subject = _subject(session)
    topic = Topic(subject_id=subject.id, name="Retrieval")
    session.add(topic)
    session.flush()
    concept = _concept(session, subject, "Hybrid search")

    note = Note(title="n", study_date=dt.date(2026, 8, 22))
    session.add(note)
    session.flush()
    block = NoteBlock(note_id=note.id, position=0, text="BM25 plus dense",
                      content_hash="h")
    session.add(block)
    session.flush()
    session.add(ConceptSource(concept_id=concept.id, note_block_id=block.id,
                              note_id=note.id))
    session.add(ReviewItem(concept_id=concept.id, dimension="explain"))
    session.add(LLMRun(task="mcq_generation", model="gemini-3.5-flash-lite",
                       concept_id=concept.id, input_tokens=100,
                       output_tokens=900, estimated_cost_usd=0.0025))
    session.flush()

    detail = graph.concept_detail(session, concept.id)

    assert detail["canonical_name"] == "Hybrid search"
    assert detail["sources"][0]["text"] == "BM25 plus dense"
    assert detail["review_items"][0]["dimension"] == "explain"
    assert detail["cost"]["generations"] == 1
    assert detail["cost"]["input_tokens"] == 100
    assert detail["cost"]["estimated_cost_usd"] == 0.0025
    assert detail["mastery"]["badge"] == "untested"


def test_an_invalidated_source_is_marked_not_hidden(session) -> None:
    subject = _subject(session)
    concept = _concept(session, subject, "Hybrid search")
    note = Note(title="n", study_date=dt.date(2026, 8, 22))
    session.add(note)
    session.flush()
    block = NoteBlock(note_id=note.id, position=0, text="Old text",
                      content_hash="h")
    session.add(block)
    session.flush()
    session.add(ConceptSource(concept_id=concept.id, note_block_id=block.id,
                              note_id=note.id,
                              invalidated_at=dt.datetime.now(dt.timezone.utc)))
    session.flush()

    detail = graph.concept_detail(session, concept.id)
    assert detail["sources"][0]["invalidated"] is True
    assert detail["sources"][0]["text"] == "Old text"


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

def test_renaming_a_concept_keeps_the_old_name_as_an_alias(app, client) -> None:
    """Spec §13.3 — "rename (old name auto-becomes an alias)"."""
    subject = client.post("/api/subjects", json={"name": "GenAI"}).json()
    created = client.post("/api/concepts", json={
        "name": "Hybrid search", "definition": "BM25 plus dense retrieval.",
        "subject_id": subject["id"],
    }).json()
    concept_id = created["concept"]["id"]

    detail = client.patch(f"/api/graph/concepts/{concept_id}",
                          json={"canonical_name": "Sparse-dense fusion"}).json()

    assert detail["canonical_name"] == "Sparse-dense fusion"
    assert "Hybrid search" in [a["alias"] for a in detail["aliases"]]
    # The old name still resolves.
    again = client.post("/api/concepts", json={
        "name": "Hybrid search", "definition": "…", "subject_id": subject["id"],
    }).json()
    assert again["action"] == "exact"
    assert again["concept"]["id"] == concept_id


def test_enabling_a_coverage_dimension_creates_its_review_item(app, client) -> None:
    subject = client.post("/api/subjects", json={"name": "GenAI"}).json()
    created = client.post("/api/concepts", json={
        "name": "Hybrid search", "definition": "BM25 plus dense.",
        "subject_id": subject["id"],
        "coverage_profile": {"recall": True, "explain": False, "apply": False,
                             "debug": False, "synthesis": False,
                             "interview": False},
    }).json()
    concept_id = created["concept"]["id"]

    client.patch(f"/api/graph/concepts/{concept_id}", json={
        "coverage_profile": {"recall": True, "explain": False, "apply": True,
                             "debug": False, "synthesis": False,
                             "interview": False},
    })

    dims = {r[0] for r in app.query("SELECT dimension FROM review_items")}
    assert "apply" in dims


def test_accepting_an_edge_that_would_close_a_cycle_is_refused(app, client) -> None:
    """Spec §8.4 — prerequisite edges must form a DAG."""
    subject = client.post("/api/subjects", json={"name": "GenAI"}).json()
    ids = []
    for name in ("A", "B", "C"):
        body = client.post("/api/concepts", json={
            "name": name, "definition": f"{name} definition.",
            "subject_id": subject["id"], "resolve": False,
        }).json()
        ids.append(body["concept"]["id"])
    a, b, c = ids

    client.post("/api/graph/edges", json={
        "source_concept_id": a, "target_concept_id": b,
        "relation_type": "prerequisite_of"})
    client.post("/api/graph/edges", json={
        "source_concept_id": b, "target_concept_id": c,
        "relation_type": "prerequisite_of"})

    # C -> A would close the loop, so it is created proposed and flagged.
    closing = client.post("/api/graph/edges", json={
        "source_concept_id": c, "target_concept_id": a,
        "relation_type": "prerequisite_of"}).json()
    assert closing["cycle_conflict"] is True
    assert closing["status"] == "proposed"

    # And accepting it is refused rather than silently allowed.
    response = client.post(f"/api/graph/edges/{closing['id']}/accept")
    assert response.status_code == 409
    assert "cycle" in response.json()["detail"].lower()


def test_flipping_an_edge_resolves_its_cycle(app, client) -> None:
    """Spec §13.2 — "accept / reject / flip direction"."""
    subject = client.post("/api/subjects", json={"name": "GenAI"}).json()
    ids = []
    for name in ("A", "B"):
        body = client.post("/api/concepts", json={
            "name": name, "definition": f"{name} definition.",
            "subject_id": subject["id"], "resolve": False,
        }).json()
        ids.append(body["concept"]["id"])
    a, b = ids

    client.post("/api/graph/edges", json={
        "source_concept_id": a, "target_concept_id": b,
        "relation_type": "prerequisite_of"})
    closing = client.post("/api/graph/edges", json={
        "source_concept_id": b, "target_concept_id": a,
        "relation_type": "prerequisite_of"}).json()
    assert closing["cycle_conflict"] is True

    flipped = client.post(f"/api/graph/edges/{closing['id']}/flip").json()

    assert flipped["source_id"] == a
    assert flipped["target_id"] == b
    assert flipped["cycle_conflict"] is False


def test_a_user_created_edge_is_accepted_immediately(app, client) -> None:
    subject = client.post("/api/subjects", json={"name": "GenAI"}).json()
    ids = []
    for name in ("A", "B"):
        body = client.post("/api/concepts", json={
            "name": name, "definition": f"{name} definition.",
            "subject_id": subject["id"], "resolve": False,
        }).json()
        ids.append(body["concept"]["id"])

    created = client.post("/api/graph/edges", json={
        "source_concept_id": ids[0], "target_concept_id": ids[1],
        "relation_type": "related_to"}).json()

    assert created["status"] == "accepted"
    assert created["cycle_conflict"] is False


def test_an_invalid_relation_type_is_refused(app, client) -> None:
    subject = client.post("/api/subjects", json={"name": "GenAI"}).json()
    ids = []
    for name in ("A", "B"):
        body = client.post("/api/concepts", json={
            "name": name, "definition": f"{name} def.",
            "subject_id": subject["id"], "resolve": False,
        }).json()
        ids.append(body["concept"]["id"])

    response = client.post("/api/graph/edges", json={
        "source_concept_id": ids[0], "target_concept_id": ids[1],
        "relation_type": "invented"})
    assert response.status_code == 400


def test_an_unknown_saved_view_is_refused(app, client) -> None:
    assert client.get("/api/graph", params={"view": "nonsense"}).status_code == 400
