"""Pipeline endpoints (spec §15, §8.5)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import LLMRun, PipelineJob
from ..pipeline import worker
from ..pipeline.stages import create_job, job_stats, unprocessed_blocks

router = APIRouter()


class RunRequest(BaseModel):
    """Spec §8 — "Scope: a subject, or all subjects"."""

    subject_id: int | None = None


class JobOut(BaseModel):
    id: int
    name: str
    status: str
    stage: str | None = None
    subject_id: int | None = None
    block_count: int
    concepts_created: int
    concepts_updated: int
    concepts_merged: int
    edges_proposed: int
    mcqs_generated: int
    error_text: str | None = None
    #: credits | auth | request | rate_limit, when the provider said something
    #: actionable. NULL means retrying is as good a guess as any.
    error_reason: str | None = None
    error_action: str | None = None
    retry_count: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class LLMRunOut(BaseModel):
    id: int
    task: str
    model: str
    prompt_version: str | None = None
    thinking_level: str | None = None
    request_mode: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    latency_ms: int | None = None
    estimated_cost_usd: float | None = None
    success: bool
    error_text: str | None = None
    created_at: datetime


class JobDetail(BaseModel):
    job: JobOut
    stats: dict
    runs: list[LLMRunOut]


class PendingSection(BaseModel):
    """One chunk as the pipeline would build it (§8.3): a heading and the
    blocks under it. The preview shows these rather than loose bullets —
    "if every bullet point becomes a block it becomes too much to look over"
    — and it is also what actually gets sent, so the list is honest."""

    key: str
    heading: str
    note_id: int
    note_title: str
    page_kind: str | None = None
    page_id: int | None = None
    block_ids: list[int]
    blocks: list["PendingBlock"]
    estimated_tokens: int
    #: True when every block in it is parked. Held-back sections are still
    #: listed, so they can be brought back.
    skipped: bool = False


class PendingBlock(BaseModel):
    """One block that would be sent, with enough text to recognise it — and
    where it came from, so the preview can take the user there."""

    note_block_id: int
    note_id: int
    note_title: str
    block_type: str
    snippet: str
    state: str          # unprocessed | stale
    #: Parked by hand, and therefore not going anywhere.
    skipped: bool = False
    #: The page this note belongs to, for "click it and go there".
    page_kind: str | None = None
    page_id: int | None = None


# PendingSection refers to PendingBlock before it is defined.
PendingSection.model_rebuild()


class PendingOut(BaseModel):
    """What the Process notes button counts, and — per consolidated addendum
    §7 — exactly which blocks it would send."""

    unprocessed_blocks: int
    subject_id: int | None = None
    blocks: list[PendingBlock] = []
    sections: list[PendingSection] = []
    estimated_tokens: int = 0


def _out(job: PipelineJob) -> JobOut:
    return JobOut.model_validate(job, from_attributes=True)


@router.get("/pipeline/pending", response_model=PendingOut)
def pending(subject_id: int | None = None,
            preview: bool = False,
            session: Session = Depends(get_session)) -> PendingOut:
    """Consolidated addendum §7 — "show the user a preview of exactly which
    blocks (with a snippet of their text) are about to be sent to Gemini …
    This is the moment the user is about to spend real money; they should see
    what's paying for it."

    The count is always returned; the block list only when asked for, so the
    button's badge stays a cheap poll.
    """
    from ..models import Note, NoteBlock
    from ..pipeline.chunking import CHARS_PER_TOKEN, ChunkBlock, chunk_blocks
    from ..tree import has_real_content, on_a_live_page

    blocks = unprocessed_blocks(session, subject_id)
    out = PendingOut(unprocessed_blocks=len(blocks), subject_id=subject_id)
    if not preview:
        return out

    def page_of(note: Note | None) -> tuple[str | None, int | None]:
        """Which page owns this note. Innermost wins: a note on a lesson is
        the lesson's, not its subtopic's."""
        if note is None:
            return None, None
        if note.lesson_id:
            return "lesson", note.lesson_id
        if note.subtopic_id:
            return "subtopic", note.subtopic_id
        if note.topic_id:
            return "topic", note.topic_id
        if note.subject_id:
            return "subject", note.subject_id
        return None, None

    seen: dict[int, tuple[str, str | None, int | None]] = {}
    rows: list[PendingBlock] = []
    for block in blocks:
        if block.note_id not in seen:
            note = session.get(Note, block.note_id)
            kind, page_id = page_of(note)
            seen[block.note_id] = (note.title if note else "(untitled)",
                                   kind, page_id)
        title, page_kind, page_id = seen[block.note_id]
        text = (block.text or "").strip()
        rows.append(PendingBlock(
            note_block_id=block.id,
            note_id=block.note_id,
            note_title=title,
            block_type=block.block_type,
            snippet=text[:160] + ("…" if len(text) > 160 else ""),
            state=("stale" if block.processed_hash is not None else "unprocessed"),
            page_kind=page_kind,
            page_id=page_id,
        ))

    out.blocks = rows
    out.estimated_tokens = sum(
        max(1, len(b.text or "") // CHARS_PER_TOKEN) for b in blocks
    )

    # …and the same thing grouped the way it will actually be sent: one entry
    # per chunk (§8.3 groups consecutive blocks under a heading), so the list
    # is a handful of sections rather than every bullet in the note. Parked
    # blocks are included here — greyed, not hidden — because the preview is
    # also where they are brought back.
    by_id = {b.id: b for b in blocks}
    candidates: dict[int, list[NoteBlock]] = {}
    for block in session.exec(
        select(NoteBlock)
        .where(NoteBlock.deleted_at.is_(None))
        .order_by(NoteBlock.note_id, NoteBlock.position)
    ).all():
        if block.id in by_id:
            candidates.setdefault(block.note_id, []).append(block)
            continue
        # A parked block only belongs in the list if it would otherwise have
        # been sent: unprocessed, real writing, on a page that still exists.
        if not block.skip_processing:
            continue
        if block.processed_hash == block.content_hash or not has_real_content(block):
            continue
        note = session.get(Note, block.note_id)
        if note is None or note.deleted_at is not None or not on_a_live_page(session, note):
            continue
        if subject_id is not None and note.subject_id != subject_id:
            continue
        candidates.setdefault(block.note_id, []).append(block)

    sections: list[PendingSection] = []
    for note_id, note_blocks in candidates.items():
        note = session.get(Note, note_id)
        title, page_kind, page_id = seen.get(
            note_id,
            (note.title if note else "(untitled)", *page_of(note)),
        )
        chunkable = [
            ChunkBlock(block_id=b.id, note_id=b.note_id,
                       block_type=b.block_type, text=b.text or "")
            for b in sorted(note_blocks, key=lambda b: b.position)
        ]
        parked = {b.id for b in note_blocks if b.skip_processing}

        for index, chunk in enumerate(chunk_blocks(chunkable)):
            heading = next(
                (b.text for b in chunk.blocks
                 if b.block_type in ("heading1", "heading2", "heading3")),
                "",
            )
            members = []
            for member in chunk.blocks:
                text = (member.text or "").strip()
                members.append(PendingBlock(
                    note_block_id=member.block_id,
                    note_id=note_id,
                    note_title=title,
                    block_type=member.block_type,
                    snippet=text[:160] + ("…" if len(text) > 160 else ""),
                    state=("stale" if by_id.get(member.block_id) is not None
                           and by_id[member.block_id].processed_hash is not None
                           else "unprocessed"),
                    skipped=member.block_id in parked,
                    page_kind=page_kind,
                    page_id=page_id,
                ))
            sections.append(PendingSection(
                key=f"{note_id}-{index}",
                heading=heading or (members[0].snippet[:60] if members else "Untitled"),
                note_id=note_id,
                note_title=title,
                page_kind=page_kind,
                page_id=page_id,
                block_ids=[m.note_block_id for m in members],
                blocks=members,
                estimated_tokens=chunk.estimated_tokens,
                skipped=all(m.note_block_id in parked for m in members),
            ))

    out.sections = sections
    return out


class SkipIn(BaseModel):
    """Park some blocks, or bring them back."""

    block_ids: list[int]
    skip: bool = True


@router.post("/pipeline/skip")
def set_skipped(payload: SkipIn,
                session: Session = Depends(get_session)) -> dict:
    """Hold blocks back from processing, and remember it.

    "Sometimes in my notes I leave some blocks which are not done but just
    left because I'm yet to study them and I don't want them processed."

    The flag lives on the block, so a section parked today is still parked
    next week — and editing that block later does not silently un-park it.
    """
    from ..models import NoteBlock

    changed = 0
    for block_id in payload.block_ids:
        block = session.get(NoteBlock, block_id)
        if block is None or block.deleted_at is not None:
            continue
        if block.skip_processing != payload.skip:
            block.skip_processing = payload.skip
            session.add(block)
            changed += 1
    session.flush()
    return {"changed": changed, "skip": payload.skip}


@router.post("/pipeline/run", response_model=JobOut, status_code=202)
def run(payload: RunRequest | None = None,
        session: Session = Depends(get_session)) -> JobOut:
    """Queue a job. Principle §1.3 — nothing is automatic; this only ever
    happens because the user pressed the button."""
    subject_id = payload.subject_id if payload else None

    if not unprocessed_blocks(session, subject_id):
        raise HTTPException(409, "Nothing to process")

    running = session.exec(
        select(PipelineJob).where(PipelineJob.status.in_(("queued", "running")))
    ).first()
    if running is not None:
        raise HTTPException(409, f"Job {running.name} is already in flight")

    job = create_job(session, subject_id=subject_id)
    worker.notify()
    return _out(job)


@router.get("/pipeline/jobs", response_model=list[JobOut])
def list_jobs(limit: int = 50,
              session: Session = Depends(get_session)) -> list[JobOut]:
    rows = session.exec(
        select(PipelineJob)
        .order_by(PipelineJob.created_at.desc())
        .limit(min(limit, 200))
    ).all()
    return [_out(j) for j in rows]


@router.get("/pipeline/jobs/{job_id}", response_model=JobDetail)
def job_detail(job_id: int,
               session: Session = Depends(get_session)) -> JobDetail:
    """Spec §8.5 — "what it created, updated, merged, and proposed; which
    items need attention; its token cost"."""
    job = session.get(PipelineJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")

    runs = session.exec(
        select(LLMRun).where(LLMRun.job_id == job_id).order_by(LLMRun.created_at)
    ).all()
    return JobDetail(
        job=_out(job),
        stats=job_stats(session, job),
        runs=[LLMRunOut.model_validate(r, from_attributes=True) for r in runs],
    )


@router.post("/pipeline/jobs/{job_id}/retry", response_model=JobOut)
def retry(job_id: int, session: Session = Depends(get_session)) -> JobOut:
    """Re-queue a failed job. It resumes from the stage that failed (§8.2)."""
    job = session.get(PipelineJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(409, f"Job is {job.status}, not failed")

    job.status = "queued"
    job.retry_count += 1
    job.error_text = None
    job.finished_at = None
    session.add(job)
    session.flush()
    worker.notify()
    return _out(job)


@router.post("/pipeline/jobs/{job_id}/cancel", response_model=JobOut)
def cancel(job_id: int, session: Session = Depends(get_session)) -> JobOut:
    job = session.get(PipelineJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status in ("succeeded", "failed"):
        raise HTTPException(409, f"Job already {job.status}")

    job.status = "cancelled"
    job.finished_at = datetime.now(timezone.utc)
    session.add(job)
    session.flush()
    return _out(job)
