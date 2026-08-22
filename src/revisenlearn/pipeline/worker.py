"""The pipeline worker (spec §8.2 **[LOCKED]**).

"The worker is a **daemon thread** started at app boot that polls
`pipeline_jobs` for `status='queued'` every 2 seconds. Not FastAPI
`BackgroundTasks` — those die with the request and lose jobs on restart."
"""

from __future__ import annotations

import logging
import os
import threading

from sqlmodel import select

from ..db import session_scope
from ..models import PipelineJob
from .stages import run_job

log = logging.getLogger(__name__)

POLL_SECONDS = 2.0

_thread: threading.Thread | None = None
_stop = threading.Event()
#: Set whenever a job is queued, so a fresh job starts immediately instead of
#: waiting out the poll interval. The 2s poll remains the backstop that catches
#: jobs left queued by a crash or restart.
_wake = threading.Event()


def notify() -> None:
    _wake.set()


def _claim_next_job() -> int | None:
    """Take the oldest queued job. One worker, so no locking dance is needed
    beyond the single write transaction."""
    with session_scope() as session:
        job = session.exec(
            select(PipelineJob)
            .where(PipelineJob.status == "queued")
            .order_by(PipelineJob.created_at, PipelineJob.id)
        ).first()
        if job is None:
            return None
        job.status = "running"
        session.add(job)
        return job.id


def _loop() -> None:
    log.info("Pipeline worker started")
    while not _stop.is_set():
        try:
            job_id = _claim_next_job()
            while job_id is not None and not _stop.is_set():
                run_job(job_id)
                job_id = _claim_next_job()
        except Exception:
            # The worker must outlive any single failure.
            log.exception("Pipeline worker loop error")
        _wake.wait(POLL_SECONDS)
        _wake.clear()
    log.info("Pipeline worker stopped")


def start_worker() -> threading.Thread | None:
    """Called at app boot. `RNL_NO_WORKER=1` disables it so tests can drive the
    stages synchronously."""
    global _thread
    if os.environ.get("RNL_NO_WORKER") == "1":
        log.info("Pipeline worker disabled (RNL_NO_WORKER=1)")
        return None
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="pipeline-worker", daemon=True)
    _thread.start()
    return _thread


def stop_worker(timeout: float = 5.0) -> None:
    global _thread
    _stop.set()
    _wake.set()
    if _thread is not None:
        _thread.join(timeout=timeout)
    _thread = None
