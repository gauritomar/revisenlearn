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


class PendingOut(BaseModel):
    """What the Process notes button counts."""

    unprocessed_blocks: int
    subject_id: int | None = None


def _out(job: PipelineJob) -> JobOut:
    return JobOut.model_validate(job, from_attributes=True)


@router.get("/pipeline/pending", response_model=PendingOut)
def pending(subject_id: int | None = None,
            session: Session = Depends(get_session)) -> PendingOut:
    return PendingOut(
        unprocessed_blocks=len(unprocessed_blocks(session, subject_id)),
        subject_id=subject_id,
    )


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
