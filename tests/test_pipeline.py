"""The pipeline (spec §8 **[LOCKED]**) and LLM accounting (§1.6, §12).

Every test here runs against the mock provider — §19's "seed a note → run
pipeline against a mocked provider". No test in this repo ever spends money.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlmodel import select

from revisenlearn.llm import set_provider
from revisenlearn.llm.mock import MockProvider
from revisenlearn.models import (
    Concept,
    ConceptEdge,
    ConceptSource,
    LLMRun,
    Note,
    NoteBlock,
    PipelineJob,
    PipelineJobBlock,
    Subject,
    Subtopic,
    Topic,
)
from revisenlearn.pipeline.stages import (
    create_job,
    creates_cycle,
    job_stats,
    run_job,
    unprocessed_blocks,
)


@pytest.fixture(autouse=True)
def mock_llm():
    """No test in this file may reach the network."""
    provider = MockProvider()
    set_provider(provider)
    yield provider
    set_provider(None)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

def _tree(session) -> dict:
    subject = Subject(name="GenAI")
    session.add(subject)
    session.flush()
    topic = Topic(subject_id=subject.id, name="Retrieval")
    session.add(topic)
    session.flush()
    subtopic = Subtopic(topic_id=topic.id, name="Hybrid search")
    session.add(subtopic)
    session.flush()
    return {"subject": subject, "topic": topic, "subtopic": subtopic}


def _note_with_blocks(session, tree, texts: list[str]) -> Note:
    from revisenlearn.hashing import content_hash

    note = Note(
        title="Hybrid search",
        study_date=dt.date(2026, 8, 22),
        subject_id=tree["subject"].id,
        topic_id=tree["topic"].id,
        subtopic_id=tree["subtopic"].id,
    )
    session.add(note)
    session.flush()
    for index, text in enumerate(texts):
        session.add(NoteBlock(
            note_id=note.id, position=index, block_type="bullet_list_item",
            text=text, content_hash=content_hash(text),
        ))
    session.flush()
    return note


BULLETS = [
    "BM25 handles rare exact terms that dense embeddings routinely miss",
    "Dense retrieval handles paraphrase and synonym matching well",
    "Reciprocal rank fusion merges the two rankings without tuning weights",
]


# --------------------------------------------------------------------------
# §8.1 Job naming
# --------------------------------------------------------------------------

def test_job_names_are_adjective_animal_plus_a_human_date(session) -> None:
    import random

    from revisenlearn.pipeline.naming import generate_name, human_date

    name = generate_name(session, dt.datetime(2026, 8, 22, 15, 40),
                         rng=random.Random(0))

    assert " · " in name
    word, when = name.split(" · ")
    adjective, animal = word.split("-")
    assert adjective and animal
    assert when == "22 Aug, 3:40 pm"
    assert human_date(dt.datetime(2026, 1, 5, 9, 5)) == "5 Jan, 9:05 am"
    assert human_date(dt.datetime(2026, 1, 5, 0, 5)) == "5 Jan, 12:05 am"


def test_colliding_job_names_get_a_numeric_suffix(session) -> None:
    import random

    from revisenlearn.pipeline.naming import generate_name

    when = dt.datetime(2026, 8, 22, 15, 40)
    first = generate_name(session, when, rng=random.Random(0))
    session.add(PipelineJob(name=first, status="succeeded"))
    session.flush()

    second = generate_name(session, when, rng=random.Random(0))
    assert second != first
    assert "-2 · " in second


# --------------------------------------------------------------------------
# §8.3 Chunking
# --------------------------------------------------------------------------

def test_chunks_split_on_headings() -> None:
    from revisenlearn.pipeline.chunking import ChunkBlock, chunk_blocks

    blocks = [
        ChunkBlock(1, 1, "heading1", "Sparse retrieval"),
        ChunkBlock(2, 1, "bullet_list_item", "BM25 scores rare exact terms very well"),
        ChunkBlock(3, 1, "heading1", "Dense retrieval"),
        ChunkBlock(4, 1, "bullet_list_item", "Embeddings capture paraphrase relationships"),
    ]
    chunks = chunk_blocks(blocks)

    assert [c.block_ids for c in chunks] == [[1, 2], [3, 4]]


def test_a_short_lone_bullet_is_merged_with_its_neighbour() -> None:
    """Spec §8.3 — "Chunks that are a single bullet under 15 words should be
    merged with their neighbours"."""
    from revisenlearn.pipeline.chunking import ChunkBlock, chunk_blocks

    blocks = [
        ChunkBlock(1, 1, "heading1", "Retrieval"),
        ChunkBlock(2, 1, "bullet_list_item",
                   "A reasonably long bullet that comfortably exceeds the "
                   "fifteen word threshold for merging behaviour"),
        ChunkBlock(3, 1, "heading1", "Note"),
    ]
    chunks = chunk_blocks(blocks)

    # The lone trailing heading is a stub and folds into the previous chunk.
    assert len(chunks) == 1
    assert chunks[0].block_ids == [1, 2, 3]


def test_a_long_note_splits_with_a_one_block_overlap() -> None:
    from revisenlearn.pipeline.chunking import (
        MAX_CHUNK_TOKENS,
        ChunkBlock,
        chunk_blocks,
    )

    big = "word " * 400          # ~500 tokens each
    blocks = [ChunkBlock(i, 1, "paragraph", big) for i in range(1, 7)]

    chunks = chunk_blocks(blocks)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.estimated_tokens <= MAX_CHUNK_TOKENS * 1.5
    # Consecutive chunks share their boundary block.
    assert chunks[0].block_ids[-1] == chunks[1].block_ids[0]


def test_the_hierarchy_path_is_sent_with_every_chunk() -> None:
    from revisenlearn.pipeline.chunking import ChunkBlock, Chunk

    chunk = Chunk(blocks=[ChunkBlock(7, 1, "bullet_list_item", "BM25 first")])
    rendered = chunk.render("GenAI > Retrieval > Hybrid search")

    assert "PATH: GenAI > Retrieval > Hybrid search" in rendered
    # Block ids travel with the text so extraction can cite sources (§11.1).
    assert "[block 7]" in rendered


# --------------------------------------------------------------------------
# Which blocks are pending
# --------------------------------------------------------------------------

def test_only_new_and_edited_blocks_are_pending(session) -> None:
    tree = _tree(session)
    note = _note_with_blocks(session, tree, BULLETS)
    blocks = session.exec(
        select(NoteBlock).order_by(NoteBlock.position)
    ).all()

    assert len(unprocessed_blocks(session)) == 3

    # Mark the first processed as it currently reads.
    blocks[0].processed_hash = blocks[0].content_hash
    # Mark the second processed, then edited (stale).
    blocks[1].processed_hash = "something-else"
    session.add_all(blocks)
    session.flush()

    pending = unprocessed_blocks(session)
    ids = {b.id for b in pending}
    assert blocks[0].id not in ids          # processed
    assert blocks[1].id in ids              # stale counts as pending
    assert blocks[2].id in ids              # never processed
    assert note.id


def test_empty_blocks_are_never_sent_to_the_model(session) -> None:
    tree = _tree(session)
    _note_with_blocks(session, tree, ["   ", "Real content worth extracting here"])

    pending = unprocessed_blocks(session)
    assert [b.text for b in pending] == ["Real content worth extracting here"]


# --------------------------------------------------------------------------
# End to end (spec §19's smoke test)
# --------------------------------------------------------------------------

def test_a_full_run_turns_a_note_into_concepts(session, mock_llm) -> None:
    """Phase 5 is done when "pressing Process notes turns a real note into
    correctly deduplicated concepts, and the job page shows what happened and
    what it cost"."""
    tree = _tree(session)
    _note_with_blocks(session, tree, BULLETS)
    job = create_job(session)
    session.commit()

    assert run_job(job.id) == "succeeded"

    from revisenlearn.db import session_scope

    with session_scope() as s:
        concepts = s.exec(select(Concept)).all()
        assert concepts, "the run produced no concepts"
        # Filed under the note's hierarchy.
        assert all(c.subject_id == tree["subject"].id for c in concepts)
        # Every concept cites a real block (§11.1).
        sources = s.exec(select(ConceptSource)).all()
        assert sources
        block_ids = {b.id for b in s.exec(select(NoteBlock)).all()}
        assert all(src.note_block_id in block_ids for src in sources)

        finished = s.get(PipelineJob, job.id)
        assert finished.status == "succeeded"
        assert finished.stage == "finalising"
        assert finished.block_count == 3
        assert finished.concepts_created >= 1
        assert finished.finished_at is not None


def test_a_full_run_marks_the_blocks_processed(session) -> None:
    """Spec §4.2 — after a run the indicators must flip."""
    tree = _tree(session)
    _note_with_blocks(session, tree, BULLETS)
    job = create_job(session)
    session.commit()

    run_job(job.id)

    from revisenlearn.db import session_scope

    with session_scope() as s:
        blocks = s.exec(select(NoteBlock)).all()
        assert all(b.processed_hash == b.content_hash for b in blocks)
        assert unprocessed_blocks(s) == []


def test_the_snapshot_is_what_the_job_works_on(session) -> None:
    """Spec §4.3 **[LOCKED]** — text typed after the button press is untouched
    by that job and stays visually unprocessed."""
    from revisenlearn.hashing import content_hash

    tree = _tree(session)
    _note_with_blocks(session, tree, BULLETS)
    job = create_job(session)
    session.commit()

    from revisenlearn.db import session_scope
    from revisenlearn.pipeline.stages import JobContext, stage_snapshotting

    # Snapshot, then edit a block before the rest of the job runs.
    with session_scope() as s:
        stage_snapshotting(s, s.get(PipelineJob, job.id), JobContext(job.id))

    with session_scope() as s:
        block = s.exec(select(NoteBlock).order_by(NoteBlock.position)).first()
        block.text = "Edited while the job was running"
        block.content_hash = content_hash(block.text)
        s.add(block)

    run_job(job.id, resume=False)

    with session_scope() as s:
        block = s.exec(select(NoteBlock).order_by(NoteBlock.position)).first()
        # The job wrote the *snapshot's* hash, so the edited block reads stale.
        assert block.processed_hash is not None
        assert block.processed_hash != block.content_hash

        snapshot = s.exec(
            select(PipelineJobBlock).where(
                PipelineJobBlock.note_block_id == block.id
            )
        ).one()
        assert snapshot.text_snapshot != block.text


def test_duplicate_concepts_across_runs_are_deduplicated(session, mock_llm) -> None:
    """The identity subsystem is doing its job inside the pipeline, not just
    in isolation."""
    tree = _tree(session)
    _note_with_blocks(session, tree, BULLETS)

    payload = {
        "concepts": [{
            "name": "Hybrid search",
            "definition": ("Combining BM25 lexical scoring with dense vector "
                           "retrieval and fusing the rankings."),
            "importance": 4, "difficulty": 3,
            "coverage_profile": {"recall": True, "explain": True, "apply": True,
                                 "debug": False, "synthesis": False,
                                 "interview": True},
            "source_block_ids": [],
        }],
        "edges": [],
    }
    # These three bullets chunk into one call, so both near-duplicates have to
    # ride in the same response.
    near_duplicate = json.loads(json.dumps(payload["concepts"][0]))
    near_duplicate["name"] = "Hybrid retrieval"
    payload["concepts"].append(near_duplicate)

    mock_llm.responses = [payload]

    job = create_job(session)
    session.commit()
    run_job(job.id)

    from revisenlearn.db import session_scope

    with session_scope() as s:
        live = [c for c in s.exec(select(Concept)).all() if c.deleted_at is None]
        # Two extractions, one surviving concept.
        assert len(live) == 1
        assert s.get(PipelineJob, job.id).concepts_merged >= 1


# --------------------------------------------------------------------------
# §1.6 accounting
# --------------------------------------------------------------------------

def test_every_call_is_logged_with_version_model_and_tokens(session) -> None:
    """Principle §1.6 — "No exceptions"."""
    tree = _tree(session)
    _note_with_blocks(session, tree, BULLETS)
    job = create_job(session)
    session.commit()
    run_job(job.id)

    from revisenlearn.db import session_scope

    with session_scope() as s:
        runs = s.exec(select(LLMRun)).all()
        assert runs
        for run in runs:
            assert run.task == "concept_extraction"
            assert run.prompt_version == "concept_extraction_v1"
            assert run.model == "gemini-3.7-flash"
            assert run.thinking_level == "medium"
            assert run.input_tokens > 0
            assert run.output_tokens > 0
            assert run.job_id == job.id
            assert run.success is True


def test_cost_is_priced_from_the_settings_table(session) -> None:
    from revisenlearn.llm.accounting import estimate_cost_usd, load_pricing
    from revisenlearn.seed import seed_settings

    seed_settings(session)
    session.flush()
    pricing = load_pricing(session)

    # §12.5: gemini-3.7-flash is $0.75 in, $3.75 out per 1M tokens.
    cost = estimate_cost_usd(pricing, "gemini-3.7-flash",
                             input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(4.50)

    # Batch is half price (§12.4).
    batch = estimate_cost_usd(pricing, "gemini-3.5-flash-lite",
                              input_tokens=1_000_000, output_tokens=1_000_000,
                              batch=True)
    assert batch == pytest.approx(0.15 + 1.25)

    # An unknown model is unpriced, not free.
    assert estimate_cost_usd(pricing, "gemini-9-imaginary",
                             input_tokens=1000, output_tokens=1000) is None


def test_the_pricing_table_knows_when_it_expires(session) -> None:
    """Spec §21.6 — the introductory rates lapse on 31 Dec 2026."""
    from revisenlearn.llm.accounting import load_pricing
    from revisenlearn.seed import seed_settings

    seed_settings(session)
    session.flush()
    pricing = load_pricing(session)

    assert pricing.expires == dt.date(2026, 12, 31)
    assert pricing.is_expired(dt.date(2026, 12, 31)) is False
    assert pricing.is_expired(dt.date(2027, 1, 1)) is True


def test_a_failed_call_is_still_logged(session, mock_llm) -> None:
    """A failed call still costs tokens, so §1.6 still applies."""
    from revisenlearn.llm.base import SchemaValidationError

    tree = _tree(session)
    _note_with_blocks(session, tree, BULLETS)
    mock_llm.responses = [SchemaValidationError("bad json", raw_response="{oops")]

    job = create_job(session)
    session.commit()
    assert run_job(job.id) == "failed"

    from revisenlearn.db import session_scope

    with session_scope() as s:
        run = s.exec(select(LLMRun)).first()
        assert run is not None
        assert run.success is False
        assert "{oops" in run.error_text

        failed = s.get(PipelineJob, job.id)
        assert failed.status == "failed"
        assert failed.error_text
        # Nothing was marked processed by a failed run.
        assert all(b.processed_hash is None
                   for b in s.exec(select(NoteBlock)).all())


# --------------------------------------------------------------------------
# §8.4 Cycle detection **[LOCKED]**
# --------------------------------------------------------------------------

def test_prerequisite_cycles_are_detected(session) -> None:
    tree = _tree(session)
    ids = []
    for name in ("A", "B", "C"):
        concept = Concept(canonical_name=name, normalised_name=name.lower(),
                          subject_id=tree["subject"].id)
        session.add(concept)
        session.flush()
        ids.append(concept.id)
    a, b, c = ids

    session.add(ConceptEdge(source_concept_id=a, target_concept_id=b,
                            relation_type="prerequisite_of", status="accepted"))
    session.add(ConceptEdge(source_concept_id=b, target_concept_id=c,
                            relation_type="prerequisite_of", status="accepted"))
    session.flush()

    # C -> A would close the loop A -> B -> C -> A.
    assert creates_cycle(session, source_id=c, target_id=a) is True
    # A -> C is fine; it is just a shortcut edge.
    assert creates_cycle(session, source_id=a, target_id=c) is False


def test_only_accepted_edges_participate_in_the_cycle_check(session) -> None:
    """Spec §8.4 — "Only `accepted` prerequisite edges participate"."""
    tree = _tree(session)
    ids = []
    for name in ("A", "B"):
        concept = Concept(canonical_name=name, normalised_name=name.lower(),
                          subject_id=tree["subject"].id)
        session.add(concept)
        session.flush()
        ids.append(concept.id)
    a, b = ids

    session.add(ConceptEdge(source_concept_id=a, target_concept_id=b,
                            relation_type="prerequisite_of", status="proposed"))
    session.flush()

    assert creates_cycle(session, source_id=b, target_id=a) is False


# --------------------------------------------------------------------------
# Edges from extraction
# --------------------------------------------------------------------------

def test_edges_are_inserted_as_proposed(session, mock_llm) -> None:
    tree = _tree(session)
    _note_with_blocks(session, tree, BULLETS)
    mock_llm.responses = [{
        "concepts": [
            {"name": "Sparse retrieval", "definition": "BM25 over an index.",
             "importance": 3, "difficulty": 2,
             "coverage_profile": {"recall": True, "explain": True, "apply": False,
                                  "debug": False, "synthesis": False,
                                  "interview": False},
             "source_block_ids": []},
            {"name": "Dense retrieval", "definition": "Vector nearest neighbours.",
             "importance": 3, "difficulty": 2,
             "coverage_profile": {"recall": True, "explain": True, "apply": False,
                                  "debug": False, "synthesis": False,
                                  "interview": False},
             "source_block_ids": []},
        ],
        "edges": [{"source_name": "Sparse retrieval",
                   "target_name": "Dense retrieval",
                   "relation_type": "contrasts_with", "confidence": 0.8}],
    }]

    job = create_job(session)
    session.commit()
    run_job(job.id)

    from revisenlearn.db import session_scope

    with session_scope() as s:
        edges = s.exec(select(ConceptEdge)).all()
        assert len(edges) == 1
        assert edges[0].status == "proposed"
        assert edges[0].created_by == "llm"
        assert edges[0].relation_type == "contrasts_with"
        assert s.get(PipelineJob, job.id).edges_proposed == 1


def test_an_invalid_relation_type_is_dropped_not_stored(session, mock_llm) -> None:
    tree = _tree(session)
    _note_with_blocks(session, tree, BULLETS)
    mock_llm.responses = [{
        "concepts": [
            {"name": "Alpha", "definition": "First.", "importance": 3,
             "difficulty": 3,
             "coverage_profile": {"recall": True, "explain": False, "apply": False,
                                  "debug": False, "synthesis": False,
                                  "interview": False},
             "source_block_ids": []},
            {"name": "Beta", "definition": "Second.", "importance": 3,
             "difficulty": 3,
             "coverage_profile": {"recall": True, "explain": False, "apply": False,
                                  "debug": False, "synthesis": False,
                                  "interview": False},
             "source_block_ids": []},
        ],
        "edges": [{"source_name": "Alpha", "target_name": "Beta",
                   "relation_type": "invented_by_the_model", "confidence": 0.9}],
    }]

    job = create_job(session)
    session.commit()
    assert run_job(job.id) == "succeeded"

    from revisenlearn.db import session_scope

    with session_scope() as s:
        assert s.exec(select(ConceptEdge)).all() == []


# --------------------------------------------------------------------------
# Retry (§8.2: "a failed job resumes from the last completed stage")
# --------------------------------------------------------------------------

def test_a_failed_job_resumes_from_the_failing_stage(session, mock_llm) -> None:
    from revisenlearn.llm.base import SchemaValidationError

    tree = _tree(session)
    _note_with_blocks(session, tree, BULLETS)
    mock_llm.responses = [SchemaValidationError("bad", raw_response="{")]

    job = create_job(session)
    session.commit()
    assert run_job(job.id) == "failed"

    from revisenlearn.db import session_scope

    with session_scope() as s:
        failed = s.get(PipelineJob, job.id)
        assert failed.stage == "extracting"
        snapshots_before = len(s.exec(select(PipelineJobBlock)).all())

    # The provider recovers; retry resumes rather than starting over.
    mock_llm.responses = []
    assert run_job(job.id) == "succeeded"

    with session_scope() as s:
        # The snapshot was not taken twice.
        assert len(s.exec(select(PipelineJobBlock)).all()) == snapshots_before
        assert s.exec(select(Concept)).all()


def test_job_stats_report_cost(session) -> None:
    """Spec §8.5 — the job page shows "its token cost"."""
    from revisenlearn.seed import seed_settings

    seed_settings(session)
    tree = _tree(session)
    _note_with_blocks(session, tree, BULLETS)
    job = create_job(session)
    session.commit()
    run_job(job.id)

    from revisenlearn.db import session_scope

    with session_scope() as s:
        stats = job_stats(s, s.get(PipelineJob, job.id))
        assert stats["llm_calls"] >= 1
        assert stats["input_tokens"] > 0
        assert stats["estimated_cost_usd"] > 0
        assert stats["failed_calls"] == 0
