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


class PendingBlock(BaseModel):
    """One block that would be sent, with enough text to recognise it — and
    where it came from, so the preview can take the user there."""

    note_block_id: int
    note_id: int
    note_title: str
    block_type: str
    snippet: str
    state: str          # unprocessed | stale
    #: The page this note belongs to, for "click it and go there".
    page_kind: str | None = None
    page_id: int | None = None


class PendingOut(BaseModel):
    """What the Process notes button counts, and — per consolidated addendum
    §7 — exactly which blocks it would send."""

    unprocessed_blocks: int
    subject_id: int | None = None
    blocks: list[PendingBlock] = []
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
    from ..models import Note
    from ..pipeline.chunking import CHARS_PER_TOKEN

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
    return out


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
