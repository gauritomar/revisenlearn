"""The staged pipeline (spec §8.2 **[LOCKED]**).

```
queued
  → snapshotting        copy blocks into pipeline_job_blocks
  → chunking            group blocks into coherent units (§8.3)
  → extracting          LLM: chunks → concepts + edges
  → resolving_identity  local: normalise, embed, match, merge
  → building_graph      insert edges as status='proposed', run cycle check
  → planning_coverage   write coverage_profile, create review_items
  → generating_mcqs     LLM (Batch API): concepts → MCQ pools
  → finalising          mark processed_hash on blocks, write job stats
  → succeeded | failed
```

"Each stage commits its own transaction; a failed job resumes from the last
completed stage on retry."
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlmodel import Session, select

from ..db import session_scope, write_lock
from ..identity import resolve_concept
from ..llm import SchemaValidationError, get_provider, task_config
from ..llm.accounting import record_run
from ..models import (
    Concept,
    ConceptEdge,
    ConceptSource,
    Note,
    NoteBlock,
    PipelineJob,
    PipelineJobBlock,
    Subject,
    Subtopic,
    Topic,
)
from ..prompts import load_prompt
from .chunking import ChunkBlock, chunk_blocks
from .schemas import ExtractionResult

log = logging.getLogger(__name__)

EXTRACTION_PROMPT_VERSION = "concept_extraction_v1"

#: The order §8.2 fixes. `planning_coverage` and `generating_mcqs` are Phase 6;
#: they are present here so the sequence is the spec's, and are no-ops until
#: that phase fills them in.
STAGES = (
    "snapshotting",
    "chunking",
    "extracting",
    "resolving_identity",
    "building_graph",
    "planning_coverage",
    "generating_mcqs",
    "finalising",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PipelineFailure(RuntimeError):
    """A stage failed.

    Carries the text for `pipeline_jobs.error_text`, and optionally the details
    of the LLM call that failed. Those details cannot be written inside the
    stage: SQLite has a single writer, so a second connection opened while the
    stage still holds its write transaction simply blocks until busy_timeout
    expires. They are written by `_fail`, after the rollback, in the same
    transaction that records the job's failure.
    """

    def __init__(self, message: str, *, llm_model: str | None = None,
                 llm_error: str | None = None, reason: str | None = None,
                 action: str | None = None) -> None:
        super().__init__(message)
        self.llm_model = llm_model
        self.llm_error = llm_error
        #: When the provider said something actionable — no credits, bad key —
        #: it travels with the failure so the job can show it instead of a
        #: Retry button pointed at a wall.
        self.reason = reason
        self.action = action


@dataclass
class JobContext:
    """Carried across stages within one run.

    Each stage commits its own transaction (§8.2), so anything held here
    outlives the session that produced it. It therefore holds **only
    primitives** — an ORM object parked here would be detached by the time the
    next stage touched it. Concepts travel as ids.
    """

    job_id: int
    chunks: list = field(default_factory=list)
    extracted: list = field(default_factory=list)
    concept_ids: set[int] = field(default_factory=set)
    pending_edges: list = field(default_factory=list)
    #: extracted concept name -> concept id
    name_to_concept_id: dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Job creation
# --------------------------------------------------------------------------

#: Block types that carry no thinking worth extracting. A `date_divider` is a
#: marker the app wrote itself (consolidated addendum §3), and an empty
#: checkbox is a line the user has not written yet — neither is worth paying a
#: model to read.
NOT_WORTH_SENDING = {"date_divider", "divider"}


def _has_content(block: NoteBlock) -> bool:
    if block.block_type in NOT_WORTH_SENDING:
        return False
    text = (block.text or "").strip()
    if block.block_type == "checklist_item":
        from ..checklist import parse_checkbox

        parsed = parse_checkbox(text)
        text = parsed[1] if parsed else text
    return bool(text.strip())


def unprocessed_blocks(session: Session,
                       subject_id: int | None = None) -> list[NoteBlock]:
    """Blocks that are new or edited-since-processed (spec §4.2), on pages
    that still exist — see `revisenlearn.tree`."""
    from ..tree import on_a_live_page
    stmt = (
        select(NoteBlock)
        .join(Note, Note.id == NoteBlock.note_id)
        .where(NoteBlock.deleted_at.is_(None), Note.deleted_at.is_(None))
    )
    if subject_id is not None:
        stmt = stmt.where(Note.subject_id == subject_id)

    live: dict[int, bool] = {}
    out: list[NoteBlock] = []
    for block in session.exec(stmt.order_by(NoteBlock.note_id,
                                            NoteBlock.position)).all():
        if block.processed_hash == block.content_hash or not _has_content(block):
            continue
        if block.note_id not in live:
            note = session.get(Note, block.note_id)
            live[block.note_id] = (note is not None
                                   and on_a_live_page(session, note))
        if live[block.note_id]:
            out.append(block)
    return out


def create_job(session: Session, subject_id: int | None = None,
               name: str | None = None) -> PipelineJob:
    """Queue a job. The worker picks it up; nothing runs in the request."""
    from .naming import generate_name

    now = _now()
    job = PipelineJob(
        name=name or generate_name(session, datetime.now()),
        status="queued",
        stage=None,
        subject_id=subject_id,
        block_count=len(unprocessed_blocks(session, subject_id)),
        created_at=now,
    )
    session.add(job)
    session.flush()
    return job


# --------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------

def stage_snapshotting(session: Session, job: PipelineJob,
                       ctx: JobContext) -> None:
    """Spec §4.3 **[LOCKED]** — copy the current text and hash of every
    unprocessed or stale block. That copy is what the job works on, so the user
    can keep writing during a run and trust the indicators."""
    existing = session.exec(
        select(PipelineJobBlock).where(PipelineJobBlock.job_id == job.id)
    ).all()
    if existing:
        return  # resuming a retry; the snapshot is already taken

    blocks = unprocessed_blocks(session, job.subject_id)
    for block in blocks:
        session.add(PipelineJobBlock(
            job_id=job.id,
            note_block_id=block.id,
            note_id=block.note_id,
            text_snapshot=block.text,
            hash_snapshot=block.content_hash,
        ))
    job.block_count = len(blocks)
    session.add(job)
    session.flush()


def stage_chunking(session: Session, job: PipelineJob, ctx: JobContext) -> None:
    snapshots = session.exec(
        select(PipelineJobBlock)
        .where(PipelineJobBlock.job_id == job.id)
        .order_by(PipelineJobBlock.note_id, PipelineJobBlock.id)
    ).all()

    by_note: dict[int, list[ChunkBlock]] = {}
    types = {
        b.id: b.block_type
        for b in session.exec(
            select(NoteBlock).where(
                NoteBlock.id.in_([s.note_block_id for s in snapshots] or [-1])
            )
        ).all()
    }
    for snap in snapshots:
        by_note.setdefault(snap.note_id, []).append(ChunkBlock(
            block_id=snap.note_block_id,
            note_id=snap.note_id,
            block_type=types.get(snap.note_block_id, "paragraph"),
            text=snap.text_snapshot,
        ))

    ctx.chunks = []
    for note_id, blocks in by_note.items():
        for chunk in chunk_blocks(blocks):
            ctx.chunks.append((note_id, chunk))


def stage_extracting(session: Session, job: PipelineJob,
                     ctx: JobContext) -> None:
    """The only LLM call in Phase 5. Every call is logged (§1.6)."""
    if not ctx.chunks:
        return

    provider = get_provider()
    cfg = task_config("concept_extraction")
    system = load_prompt(EXTRACTION_PROMPT_VERSION)

    ctx.extracted = []
    for note_id, chunk in ctx.chunks:
        path = _hierarchy_path(session, note_id)
        try:
            result = provider.generate_structured(
                system_instruction=system,
                user_input=chunk.render(path),
                model=cfg["model"],
                schema=ExtractionResult,
                thinking_level=cfg.get("thinking_level"),
                prompt_version=EXTRACTION_PROMPT_VERSION,
            )
        except SchemaValidationError as exc:
            raise PipelineFailure(
                f"Extraction returned unusable JSON: {exc}",
                llm_model=cfg["model"], llm_error=exc.raw_response,
            ) from None
        except Exception as exc:
            raise PipelineFailure(
                f"Extraction failed: {exc}",
                llm_model=cfg["model"], llm_error=str(exc),
                reason=getattr(exc, "reason", None),
                action=getattr(exc, "action", None),
            ) from None

        record_run(session, task="concept_extraction", result=result,
                   job_id=job.id, prompt_version=EXTRACTION_PROMPT_VERSION)
        ctx.extracted.append((note_id, chunk, result.parsed))


def _hierarchy_path(session: Session, note_id: int) -> str:
    """The Subject/Topic/Subtopic path, plus any Lessons the note is linked to.

    Addendum §8: lesson names are "additive context only — extraction still
    works exactly as specced when no Lesson link exists".
    """
    note = session.get(Note, note_id)
    if note is None:
        return ""
    parts: list[str] = []
    if note.subject_id:
        subject = session.get(Subject, note.subject_id)
        if subject:
            parts.append(subject.name)
    if note.topic_id:
        topic = session.get(Topic, note.topic_id)
        if topic:
            parts.append(topic.name)
    if note.subtopic_id:
        subtopic = session.get(Subtopic, note.subtopic_id)
        if subtopic:
            parts.append(subtopic.name)

    path = " > ".join(parts)

    from ..models import Lesson, NoteLessonLink

    links = session.exec(
        select(NoteLessonLink).where(NoteLessonLink.note_id == note_id)
    ).all()
    names = []
    for link in links:
        lesson = session.get(Lesson, link.lesson_id)
        if lesson is not None and lesson.deleted_at is None:
            names.append(lesson.name)
    if names:
        path = f"{path} | Lessons: {', '.join(sorted(names))}" if path \
            else f"Lessons: {', '.join(sorted(names))}"
    return path


def stage_resolving_identity(session: Session, job: PipelineJob,
                             ctx: JobContext) -> None:
    """Local: normalise, embed, match, merge (spec §7.2). No model call."""
    created = updated = merged = 0

    for note_id, chunk, extraction in ctx.extracted:
        note = session.get(Note, note_id)
        for item in extraction.concepts:
            result = resolve_concept(
                session,
                name=item.name,
                definition=item.definition,
                subject_id=note.subject_id if note else None,
                topic_id=note.topic_id if note else None,
                subtopic_id=note.subtopic_id if note else None,
                importance=float(item.importance),
                difficulty=float(item.difficulty),
                coverage_profile=item.coverage_profile.model_dump(),
                job_id=job.id,
            )
            concept = result.concept
            # Store the id, not the instance: this survives the commit.
            ctx.name_to_concept_id[item.name] = concept.id
            ctx.concept_ids.add(concept.id)

            if result.action == "new":
                created += 1
            elif result.action == "auto_merge":
                merged += 1
            else:
                updated += 1

            _attach_sources(session, concept, item.source_block_ids or
                            chunk.block_ids, note_id, job.id)

        for edge in extraction.edges:
            ctx.pending_edges.append(edge)

    job.concepts_created = created
    job.concepts_updated = updated
    job.concepts_merged = merged
    session.add(job)
    session.flush()


def _attach_sources(session: Session, concept: Concept, block_ids: list[int],
                    note_id: int, job_id: int) -> None:
    known = {
        b.id for b in session.exec(
            select(NoteBlock).where(NoteBlock.id.in_(block_ids or [-1]))
        ).all()
    }
    for block_id in block_ids:
        if block_id not in known:
            continue  # the model invented a block id
        existing = session.exec(
            select(ConceptSource).where(
                ConceptSource.concept_id == concept.id,
                ConceptSource.note_block_id == block_id,
                ConceptSource.invalidated_at.is_(None),
            )
        ).first()
        if existing is not None:
            continue
        session.add(ConceptSource(concept_id=concept.id, note_block_id=block_id,
                                  note_id=note_id, job_id=job_id))
    session.flush()


def stage_building_graph(session: Session, job: PipelineJob,
                         ctx: JobContext) -> None:
    """Insert edges as `status='proposed'` and run the §8.4 cycle check."""
    proposed = 0

    for edge in ctx.pending_edges:
        if not edge.is_valid_relation():
            continue
        source_id = ctx.name_to_concept_id.get(edge.source_name)
        target_id = ctx.name_to_concept_id.get(edge.target_name)
        if source_id is None or target_id is None or source_id == target_id:
            continue

        duplicate = session.exec(
            select(ConceptEdge).where(
                ConceptEdge.source_concept_id == source_id,
                ConceptEdge.target_concept_id == target_id,
                ConceptEdge.relation_type == edge.relation_type,
                ConceptEdge.deleted_at.is_(None),
            )
        ).first()
        if duplicate is not None:
            continue

        session.add(ConceptEdge(
            source_concept_id=source_id,
            target_concept_id=target_id,
            relation_type=edge.relation_type,
            confidence=edge.confidence,
            created_by="llm",
            status="proposed",
            job_id=job.id,
        ))
        proposed += 1

    session.flush()
    job.edges_proposed = proposed
    session.add(job)
    session.flush()


def creates_cycle(session: Session, source_id: int, target_id: int) -> bool:
    """Spec §8.4 **[LOCKED]** — `prerequisite_of` edges must form a DAG.

    DFS from the target: if the source is reachable, the new edge closes a
    loop. "Only `accepted` prerequisite edges participate in the reachability
    check."
    """
    edges = session.exec(
        select(ConceptEdge).where(
            ConceptEdge.relation_type == "prerequisite_of",
            ConceptEdge.status == "accepted",
            ConceptEdge.deleted_at.is_(None),
        )
    ).all()

    adjacency: dict[int, list[int]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source_concept_id, []).append(
            edge.target_concept_id
        )

    seen: set[int] = set()
    stack = [target_id]
    while stack:
        node = stack.pop()
        if node == source_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, []))
    return False


from .coverage import stage_planning_coverage  # noqa: E402  (§10.2)
from .mcqs import stage_generating_mcqs  # noqa: E402  (§9.1)


def stage_finalising(session: Session, job: PipelineJob,
                     ctx: JobContext) -> None:
    """Mark `processed_hash` on the blocks this job snapshotted.

    The hash written is the *snapshot's*, not the block's current hash: if the
    user edited while the job ran, that block must read as stale, not
    processed (§4.3).
    """
    snapshots = session.exec(
        select(PipelineJobBlock).where(PipelineJobBlock.job_id == job.id)
    ).all()
    ids = [s.note_block_id for s in snapshots]
    blocks = {
        b.id: b for b in session.exec(
            select(NoteBlock).where(NoteBlock.id.in_(ids or [-1]))
        ).all()
    }
    for snap in snapshots:
        block = blocks.get(snap.note_block_id)
        if block is None:
            continue
        block.processed_hash = snap.hash_snapshot
        session.add(block)
    session.flush()


STAGE_FUNCTIONS = {
    "snapshotting": stage_snapshotting,
    "chunking": stage_chunking,
    "extracting": stage_extracting,
    "resolving_identity": stage_resolving_identity,
    "building_graph": stage_building_graph,
    "planning_coverage": stage_planning_coverage,
    "generating_mcqs": stage_generating_mcqs,
    "finalising": stage_finalising,
}


# --------------------------------------------------------------------------
# Running a job
# --------------------------------------------------------------------------

def run_job(job_id: int, resume: bool = True) -> str:
    """Run every stage, each in its own transaction (§8.2).

    Returns the final status. Never raises: a failed job is a recorded state,
    not an exception the worker has to survive.
    """
    with session_scope() as session:
        job = session.get(PipelineJob, job_id)
        if job is None:
            return "missing"
        job.status = "running"
        job.started_at = job.started_at or _now()
        start_at = _resume_index(job.stage) if resume else 0
        session.add(job)

    ctx = JobContext(job_id=job_id)

    for stage in STAGES[start_at:]:
        try:
            with write_lock, session_scope() as session:
                job = session.get(PipelineJob, job_id)
                if job is None:
                    return "missing"
                if job.status == "cancelled":
                    return "cancelled"
                job.stage = stage
                session.add(job)
                session.flush()

                STAGE_FUNCTIONS[stage](session, job, ctx)
        except PipelineFailure as exc:
            return _fail(job_id, str(exc), stage=stage, failure=exc)
        except Exception as exc:  # a stage bug must not kill the worker
            log.exception("Pipeline stage %s failed", stage)
            return _fail(job_id, f"{stage}: {exc}", stage=stage)

    with session_scope() as session:
        job = session.get(PipelineJob, job_id)
        if job is None:
            return "missing"
        job.status = "succeeded"
        job.stage = "finalising"
        job.finished_at = _now()
        job.error_text = None
        session.add(job)
    log.info("Pipeline job %s succeeded", job_id)
    return "succeeded"


def _resume_index(stage: str | None) -> int:
    """Where a retry picks up (spec §8.2).

    Always the beginning, and deliberately so. Extraction's output lives only
    in the job context, never in a table, so resuming at a later stage would
    find an empty context and quietly "succeed" having done nothing. The
    stages before extraction are cheap and idempotent — snapshotting returns
    early when a snapshot exists, chunking is pure — so replaying them is free.

    Replaying *extraction* is not free: a retry spends tokens again. That is
    the honest cost of not persisting model output, which §6's schema has no
    table for. §7.2 identity resolution means the second run deduplicates
    rather than duplicating, so the result is correct, just not free.

    `stage` is still recorded on the job so the §8.5 detail page can say where
    it broke.
    """
    return 0


def _fail(job_id: int, message: str, stage: str | None = None,
          failure: PipelineFailure | None = None) -> str:
    """Record the failure.

    The failing stage is re-written here because the transaction that set it
    was rolled back along with the stage's own work — without this the job
    would report the last *successful* stage, and a retry would resume one
    stage too early.
    """
    with session_scope() as session:
        job = session.get(PipelineJob, job_id)
        if job is not None:
            job.status = "failed"
            if stage is not None:
                job.stage = stage
            job.error_text = message[:8000]
            job.error_reason = failure.reason if failure is not None else None
            job.error_action = failure.action if failure is not None else None
            job.finished_at = _now()
            session.add(job)

        # §1.6 allows no exceptions: a call that was made and billed is logged
        # even though the stage that made it rolled back.
        if failure is not None and failure.llm_model is not None:
            record_run(session, task="concept_extraction", job_id=job_id,
                       model=failure.llm_model,
                       prompt_version=EXTRACTION_PROMPT_VERSION,
                       success=False,
                       error_text=(failure.llm_error or message)[:8000])
    log.error("Pipeline job %s failed: %s", job_id, message)
    return "failed"


def job_stats(session: Session, job: PipelineJob) -> dict:
    """What the §8.5 job detail page reports, including cost."""
    from ..models import LLMRun

    runs = session.exec(
        select(LLMRun).where(LLMRun.job_id == job.id)
    ).all()
    return {
        "llm_calls": len(runs),
        "input_tokens": sum(r.input_tokens for r in runs),
        "output_tokens": sum(r.output_tokens for r in runs),
        "cached_tokens": sum(r.cached_tokens for r in runs),
        "estimated_cost_usd": round(
            sum(r.estimated_cost_usd or 0.0 for r in runs), 6
        ),
        "unpriced_calls": sum(1 for r in runs if r.estimated_cost_usd is None),
        "failed_calls": sum(1 for r in runs if not r.success),
    }
