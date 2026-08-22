"""Concept identity (spec §7 **[LOCKED]**).

"This subsystem determines whether the app is usable in three months. Treat it
as first-class." So it is tested with the real embedding model, not a stub —
the thresholds in §7.2 are claims about `bge-small-en-v1.5` specifically, and a
fake embedder would prove nothing about them.

Phase 4 is *done when* "two manually created near-duplicate concepts merge
correctly and reversibly" (§18).
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlmodel import select

from revisenlearn.identity import (
    invalidate_sources_for_block,
    merge_concepts,
    most_similar,
    normalise,
    resolve_concept,
    revert_merge,
)
from revisenlearn.models import (
    MCQ,
    Concept,
    ConceptAlias,
    ConceptEdge,
    ConceptMerge,
    ConceptSource,
    Note,
    NoteBlock,
    ReviewItem,
    ReviewLog,
    Subject,
)


# --------------------------------------------------------------------------
# §7.1 Normalisation
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Hybrid Search", "hybrid search"),
        ("  Hybrid   Search  ", "hybrid search"),
        ("Hybrid-Search!", "hybrid search"),
        # trailing parenthetical acronym is stripped
        ("Retrieval Augmented Generation (RAG)", "retrieval augmented generation"),
        ("Reciprocal Rank Fusion (RRF)", "reciprocal rank fusion"),
        # singularise a trailing "s" only when the remainder is >= 4 chars
        ("Embeddings", "embedding"),
        ("Transformers", "transformer"),
        ("Vector DBs", "vector db"),      # remainder "vector db" is long enough
        ("Gas", "gas"),                   # remainder "ga" is too short
        ("Loss", "loss"),                 # -ss is never singularised
        ("Bias", "bias"),
        ("", ""),
    ],
)
def test_normalisation(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def test_normalisation_is_idempotent() -> None:
    for raw in ["Retrieval Augmented Generation (RAG)", "Embeddings", "K-NN Search"]:
        once = normalise(raw)
        assert normalise(once) == once


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _subject(session, name: str = "GenAI") -> Subject:
    subject = Subject(name=name)
    session.add(subject)
    session.flush()
    return subject


HYBRID = (
    "Hybrid search",
    "Combining BM25 lexical scoring with dense vector retrieval and fusing "
    "the rankings.",
)
HYBRID_NEAR = (
    "Hybrid retrieval",
    "Combining BM25 lexical scoring with dense vector retrieval and fusing "
    "the rankings.",
)
CHUNKING = (
    "Chunking strategy",
    "How to split documents into passages before embedding them.",
)
RRF_LONG = (
    "Reciprocal rank fusion",
    "A method to merge two ranked lists by summing reciprocal ranks.",
)
RRF_SHORT = (
    "RRF",
    "Merging ranked lists by summing the reciprocal of each document rank.",
)


# --------------------------------------------------------------------------
# §7.2 Matching, in order
# --------------------------------------------------------------------------

def test_exact_normalised_match_returns_the_same_concept(session) -> None:
    subject = _subject(session)
    first = resolve_concept(session, *HYBRID, subject_id=subject.id)
    assert first.action == "new"

    # A different spelling that normalises identically.
    again = resolve_concept(session, "  hybrid   search!  ", "Anything at all.",
                            subject_id=subject.id)

    assert again.action == "exact"
    assert again.concept.id == first.concept.id
    assert len(session.exec(select(Concept)).all()) == 1


def test_an_exact_match_records_the_new_spelling_as_an_alias(session) -> None:
    subject = _subject(session)
    created = resolve_concept(session, *HYBRID, subject_id=subject.id)

    resolve_concept(session, "Hybrid Search (HS)", "…", subject_id=subject.id)

    aliases = {
        a.alias for a in session.exec(
            select(ConceptAlias).where(
                ConceptAlias.concept_id == created.concept.id
            )
        ).all()
    }
    assert "Hybrid search" in aliases
    assert "Hybrid Search (HS)" in aliases


def test_a_match_against_an_alias_counts_as_exact(session) -> None:
    subject = _subject(session)
    created = resolve_concept(session, *RRF_LONG, subject_id=subject.id)
    from revisenlearn.identity import _add_alias_if_new

    _add_alias_if_new(session, created.concept, "RRF", source="manual")

    found = resolve_concept(session, "rrf", "…", subject_id=subject.id)
    assert found.action == "exact"
    assert found.concept.id == created.concept.id


def test_near_duplicates_auto_merge(session) -> None:
    """Spec §7.2 — ``sim >= 0.92`` auto-merges. This is half of Phase 4's
    done-when."""
    subject = _subject(session)
    original = resolve_concept(session, *HYBRID, subject_id=subject.id)
    assert original.action == "new"

    duplicate = resolve_concept(session, *HYBRID_NEAR, subject_id=subject.id)

    assert duplicate.action == "auto_merge"
    assert duplicate.similarity >= 0.92
    # The caller gets the surviving concept back, not the duplicate.
    assert duplicate.concept.id == original.concept.id

    row = session.exec(select(ConceptMerge)).one()
    assert row.decided_by == "auto"
    assert row.merged_into_id == original.concept.id


def test_a_middling_match_goes_to_the_merge_queue(session) -> None:
    """``0.82 <= sim < 0.92`` creates the concept normally *and* writes a
    ``decided_by=NULL`` row. That NULL is the queue."""
    subject = _subject(session)
    first = resolve_concept(session, *RRF_LONG, subject_id=subject.id)

    second = resolve_concept(session, *RRF_SHORT, subject_id=subject.id)

    assert second.action == "queued"
    assert 0.82 <= second.similarity < 0.92
    # Both concepts exist and are active.
    assert second.concept.id != first.concept.id
    assert second.concept.status == "active"

    queued = session.exec(select(ConceptMerge)).one()
    assert queued.decided_by is None
    assert queued.merged_from_id == second.concept.id
    assert queued.merged_into_id == first.concept.id


def test_an_unrelated_concept_is_new(session) -> None:
    subject = _subject(session)
    resolve_concept(session, *HYBRID, subject_id=subject.id)

    other = resolve_concept(session, *CHUNKING, subject_id=subject.id)

    assert other.action == "new"
    assert other.similarity < 0.82
    assert len(session.exec(select(Concept)).all()) == 2


def test_matching_is_scoped_to_the_subject(session) -> None:
    """Spec §7.2 compares "against all active concepts in the same Subject"."""
    genai = _subject(session, "GenAI")
    systems = _subject(session, "Systems")

    resolve_concept(session, *HYBRID, subject_id=genai.id)
    in_other = resolve_concept(session, *HYBRID_NEAR, subject_id=systems.id)

    assert in_other.action == "new"
    assert len(session.exec(select(Concept)).all()) == 2


def test_thresholds_come_from_settings(session) -> None:
    """Spec §7.2 — "Thresholds live in settings and are editable"."""
    import json

    from revisenlearn.models import Setting

    subject = _subject(session)
    session.add(Setting(key="similarity_thresholds",
                        value_json=json.dumps({"auto_merge": 0.99,
                                               "merge_queue": 0.98})))
    session.flush()

    resolve_concept(session, *HYBRID, subject_id=subject.id)
    result = resolve_concept(session, *HYBRID_NEAR, subject_id=subject.id)

    # 0.988 would auto-merge at the default 0.92, but not at 0.99.
    assert result.action == "queued"
    assert len(session.exec(select(Concept)).all()) == 2


def test_most_similar_reports_the_best_match(session) -> None:
    subject = _subject(session)
    resolve_concept(session, *CHUNKING, subject_id=subject.id)
    hybrid = resolve_concept(session, *HYBRID, subject_id=subject.id)

    match, score = most_similar(session, *HYBRID_NEAR, subject_id=subject.id)

    assert match.id == hybrid.concept.id
    assert score > 0.9


# --------------------------------------------------------------------------
# §7.3 Merge semantics **[LOCKED]**
# --------------------------------------------------------------------------

def _concept(session, subject, name, definition) -> Concept:
    return resolve_concept(session, name, definition,
                           subject_id=subject.id).concept


def test_merge_moves_names_sources_edges_and_mcqs(session) -> None:
    subject = _subject(session)
    a = _concept(session, subject, "Sparse retrieval", "BM25 over an inverted index.")
    b = _concept(session, subject, "Dense retrieval", "Embedding nearest neighbour search.")
    other = _concept(session, subject, "Chunking", "Splitting documents.")

    note = Note(title="n", study_date=dt.date(2026, 8, 22))
    session.add(note)
    session.flush()
    block = NoteBlock(note_id=note.id, position=0, text="t", content_hash="h")
    session.add(block)
    session.flush()

    session.add(ConceptSource(concept_id=a.id, note_block_id=block.id,
                              note_id=note.id))
    session.add(ConceptEdge(source_concept_id=a.id, target_concept_id=other.id,
                            relation_type="related_to"))
    session.add(MCQ(concept_id=a.id, dimension="recall", stem="?",
                    options_json="[]", correct_option_id="a"))
    session.flush()

    merge_concepts(session, merged_from=a, merged_into=b, decided_by="user")

    # A's canonical name is now an alias of B.
    aliases = {al.alias for al in session.exec(
        select(ConceptAlias).where(ConceptAlias.concept_id == b.id)).all()}
    assert "Sparse retrieval" in aliases

    # Sources, edges and MCQs all point at B.
    assert session.exec(select(ConceptSource)).one().concept_id == b.id
    assert session.exec(select(ConceptEdge)).one().source_concept_id == b.id
    assert session.exec(select(MCQ)).one().concept_id == b.id

    # A is archived, not deleted.
    session.refresh(a)
    assert a.status == "archived"
    assert a.deleted_at is not None
    assert session.get(Concept, a.id) is not None


def test_merge_never_touches_note_content(session) -> None:
    """Spec §7.3 — "No note content is ever touched by a merge"."""
    subject = _subject(session)
    a = _concept(session, subject, "Sparse retrieval", "BM25 over an index.")
    b = _concept(session, subject, "Dense retrieval", "Vector search.")

    note = Note(title="Original title", study_date=dt.date(2026, 8, 22))
    session.add(note)
    session.flush()
    block = NoteBlock(note_id=note.id, position=0,
                      text="Untouched note text", content_hash="h")
    session.add(block)
    session.flush()
    session.add(ConceptSource(concept_id=a.id, note_block_id=block.id,
                              note_id=note.id))
    session.flush()

    merge_concepts(session, merged_from=a, merged_into=b)

    session.refresh(note)
    session.refresh(block)
    assert note.title == "Original title"
    assert block.text == "Untouched note text"
    assert block.deleted_at is None


def test_merge_drops_self_edges_and_duplicates(session) -> None:
    subject = _subject(session)
    a = _concept(session, subject, "Sparse retrieval", "BM25.")
    b = _concept(session, subject, "Dense retrieval", "Vectors.")
    other = _concept(session, subject, "Chunking", "Splitting.")

    # Would become a self-edge once A becomes B.
    session.add(ConceptEdge(source_concept_id=a.id, target_concept_id=b.id,
                            relation_type="related_to"))
    # Would duplicate an edge B already has.
    session.add(ConceptEdge(source_concept_id=a.id, target_concept_id=other.id,
                            relation_type="related_to"))
    session.add(ConceptEdge(source_concept_id=b.id, target_concept_id=other.id,
                            relation_type="related_to"))
    session.flush()

    merge_concepts(session, merged_from=a, merged_into=b)

    live = [e for e in session.exec(select(ConceptEdge)).all()
            if e.deleted_at is None]
    assert len(live) == 1
    assert live[0].source_concept_id == b.id
    assert live[0].target_concept_id == other.id
    # Nothing was hard-deleted (principle §1.7).
    assert len(session.exec(select(ConceptEdge)).all()) == 3


def test_merge_keeps_bs_fsrs_state_and_repoints_as_logs(session) -> None:
    """Spec §7.3 — "keep B's FSRS state, keep both items' review_logs, and
    repoint A's logs to B's item"."""
    subject = _subject(session)
    a = _concept(session, subject, "Sparse retrieval", "BM25.")
    b = _concept(session, subject, "Dense retrieval", "Vectors.")

    a_item = ReviewItem(concept_id=a.id, dimension="explain",
                        fsrs_stability=1.0, reps=2, lapses=1)
    b_item = ReviewItem(concept_id=b.id, dimension="explain",
                        fsrs_stability=9.0, reps=5, lapses=0)
    # A also has a dimension B lacks.
    a_only = ReviewItem(concept_id=a.id, dimension="apply",
                        fsrs_stability=3.0, reps=1)
    session.add_all([a_item, b_item, a_only])
    session.flush()

    session.add(ReviewLog(review_item_id=a_item.id, concept_id=a.id,
                          dimension="explain", rating=1))
    session.add(ReviewLog(review_item_id=b_item.id, concept_id=b.id,
                          dimension="explain", rating=3))
    session.flush()

    merge_concepts(session, merged_from=a, merged_into=b)

    items = {i.dimension: i for i in session.exec(
        select(ReviewItem).where(ReviewItem.concept_id == b.id)).all()}
    # B's FSRS state survived; A's was folded in as counts only.
    assert items["explain"].fsrs_stability == 9.0
    assert items["explain"].reps == 7        # 5 + 2
    assert items["explain"].lapses == 1      # 0 + 1
    # The dimension only A had came across intact.
    assert items["apply"].fsrs_stability == 3.0

    # Both logs survive and both now point at B.
    logs = session.exec(select(ReviewLog)).all()
    assert len(logs) == 2
    assert all(log.concept_id == b.id for log in logs)
    assert {log.review_item_id for log in logs} == {items["explain"].id}


def test_a_concept_cannot_merge_into_itself(session) -> None:
    subject = _subject(session)
    a = _concept(session, subject, "Sparse retrieval", "BM25.")
    with pytest.raises(ValueError):
        merge_concepts(session, merged_from=a, merged_into=a)


# --------------------------------------------------------------------------
# Reversibility — the other half of Phase 4's done-when
# --------------------------------------------------------------------------

def test_a_merge_can_be_reverted(session) -> None:
    subject = _subject(session)
    original = resolve_concept(session, *HYBRID, subject_id=subject.id)
    duplicate = resolve_concept(session, *HYBRID_NEAR, subject_id=subject.id)
    assert duplicate.action == "auto_merge"

    row = session.exec(select(ConceptMerge)).one()
    archived_id = row.merged_from_id

    restored = revert_merge(session, row)

    assert restored.id == archived_id
    assert restored.status == "active"
    assert restored.deleted_at is None
    assert row.reverted_at is not None

    # Both concepts are live again.
    live = [c for c in session.exec(select(Concept)).all()
            if c.deleted_at is None]
    assert len(live) == 2

    # The alias the merge added to B is gone again.
    b_aliases = {a.alias for a in session.exec(
        select(ConceptAlias).where(
            ConceptAlias.concept_id == row.merged_into_id)).all()}
    assert "Hybrid retrieval" not in b_aliases


def test_a_merge_cannot_be_reverted_twice(session) -> None:
    subject = _subject(session)
    resolve_concept(session, *HYBRID, subject_id=subject.id)
    resolve_concept(session, *HYBRID_NEAR, subject_id=subject.id)

    row = session.exec(select(ConceptMerge)).one()
    revert_merge(session, row)

    with pytest.raises(ValueError):
        revert_merge(session, row)


# --------------------------------------------------------------------------
# §7.4 Stale concepts
# --------------------------------------------------------------------------

def test_losing_every_source_makes_a_concept_stale_but_still_scheduled(session) -> None:
    """Spec §7.4 — "Keep scheduling its review items normally. The user may
    have reviewed it twenty times; losing the source text does not mean losing
    the knowledge"."""
    subject = _subject(session)
    concept = _concept(session, subject, "Hybrid search", HYBRID[1])

    note = Note(title="n", study_date=dt.date(2026, 8, 22))
    session.add(note)
    session.flush()
    block = NoteBlock(note_id=note.id, position=0, text="t", content_hash="h")
    session.add(block)
    session.flush()
    session.add(ConceptSource(concept_id=concept.id, note_block_id=block.id,
                              note_id=note.id))
    item = ReviewItem(concept_id=concept.id, dimension="explain", reps=20)
    session.add(item)
    session.flush()

    assert concept.status == "active"

    invalidate_sources_for_block(session, block.id)

    session.refresh(concept)
    session.refresh(item)
    assert concept.status == "stale"
    # Still scheduled: not suspended, history intact.
    assert item.suspended is False
    assert item.reps == 20


def test_a_concept_with_another_valid_source_stays_active(session) -> None:
    subject = _subject(session)
    concept = _concept(session, subject, "Hybrid search", HYBRID[1])

    note = Note(title="n", study_date=dt.date(2026, 8, 22))
    session.add(note)
    session.flush()
    blocks = []
    for i in range(2):
        block = NoteBlock(note_id=note.id, position=i, text=f"t{i}",
                          content_hash=f"h{i}")
        session.add(block)
        session.flush()
        blocks.append(block)
        session.add(ConceptSource(concept_id=concept.id,
                                  note_block_id=block.id, note_id=note.id))
    session.flush()

    invalidate_sources_for_block(session, blocks[0].id)

    session.refresh(concept)
    assert concept.status == "active"
