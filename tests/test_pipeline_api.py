"""Pipeline endpoints and the daemon worker (spec §8, §15).

These drive a real server with the worker thread running, so the whole
"press the button, a job appears, the worker picks it up" path is exercised.
The server is started with the mock provider — no test spends money.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from conftest import start_app


@pytest.fixture
def pipeline_app(db_path: Path):
    """A server with the worker running and the mock LLM selected."""
    instance = start_app(db_path, extra_env={"RNL_LLM_PROVIDER": "mock"})
    try:
        yield instance
    finally:
        instance.stop()


@pytest.fixture
def pc(pipeline_app):
    with httpx.Client(base_url=pipeline_app.base_url, timeout=60) as client:
        yield client


def _note(client) -> dict:
    subject = client.post("/api/subjects", json={"name": "GenAI"}).json()
    topic = client.post("/api/topics",
                        json={"subject_id": subject["id"],
                              "name": "Retrieval"}).json()
    subtopic = client.post("/api/subtopics",
                           json={"topic_id": topic["id"],
                                 "name": "Hybrid search"}).json()
    note = client.post("/api/notes/ensure",
                       json={"subtopic_id": subtopic["id"]}).json()
    client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [
            {"id": None, "position": 0, "block_type": "bullet_list_item",
             "text": "BM25 handles rare exact terms that embeddings miss"},
            {"id": None, "position": 1, "block_type": "bullet_list_item",
             "text": "Dense retrieval handles paraphrase and synonyms well"},
        ]},
    )
    return {"subject": subject, "note": note}


def _wait_for(client, job_id: int, timeout: float = 45.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/pipeline/jobs/{job_id}").json()
        if body["job"]["status"] in ("succeeded", "failed", "cancelled"):
            return body
        time.sleep(0.2)
    raise AssertionError(f"Job {job_id} never finished")


def test_pending_counts_unprocessed_blocks(pc) -> None:
    assert pc.get("/api/pipeline/pending").json()["unprocessed_blocks"] == 0
    _note(pc)
    assert pc.get("/api/pipeline/pending").json()["unprocessed_blocks"] == 2


def test_pressing_process_notes_runs_a_job_end_to_end(pipeline_app, pc) -> None:
    """Phase 5's done-when: "pressing Process notes turns a real note into
    correctly deduplicated concepts, and the job page shows what happened and
    what it cost"."""
    _note(pc)

    queued = pc.post("/api/pipeline/run", json={}).json()
    assert queued["status"] in ("queued", "running")
    assert " · " in queued["name"]          # §8.1 naming

    detail = _wait_for(pc, queued["id"])

    assert detail["job"]["status"] == "succeeded"
    assert detail["job"]["block_count"] == 2
    assert detail["job"]["concepts_created"] >= 1

    # §8.5 — the page shows what it cost.
    assert detail["stats"]["llm_calls"] >= 1
    assert detail["stats"]["input_tokens"] > 0
    assert detail["stats"]["estimated_cost_usd"] > 0
    assert detail["runs"][0]["prompt_version"] == "concept_extraction_v1"
    assert detail["runs"][0]["model"] == "gemini-3.7-flash"

    # Concepts landed, and the blocks now read as processed.
    assert pipeline_app.query("SELECT count(*) FROM concepts")[0][0] >= 1
    assert pc.get("/api/pipeline/pending").json()["unprocessed_blocks"] == 0
    assert pc.get("/api/concepts").json()


def test_nothing_to_process_is_refused(pc) -> None:
    """Principle §1.3 — the system never silently spends money."""
    assert pc.post("/api/pipeline/run", json={}).status_code == 409


def test_two_jobs_cannot_run_at_once(pc) -> None:
    _note(pc)
    first = pc.post("/api/pipeline/run", json={}).json()

    second = pc.post("/api/pipeline/run", json={})
    assert second.status_code == 409
    assert "already in flight" in second.json()["detail"]

    _wait_for(pc, first["id"])


def test_a_job_can_be_scoped_to_a_subject(pipeline_app, pc) -> None:
    """Spec §8 — "Scope: a subject, or all subjects"."""
    first = _note(pc)
    other = pc.post("/api/subjects", json={"name": "Systems"}).json()
    topic = pc.post("/api/topics",
                    json={"subject_id": other["id"], "name": "Databases"}).json()
    subtopic = pc.post("/api/subtopics",
                       json={"topic_id": topic["id"], "name": "Indexing"}).json()
    note = pc.post("/api/notes/ensure",
                   json={"subtopic_id": subtopic["id"]}).json()
    pc.put(f"/api/notes/{note['id']}/blocks",
           json={"blocks": [{"id": None, "position": 0,
                             "block_type": "bullet_list_item",
                             "text": "B-trees keep range scans cheap on disk"}]})

    scoped = pc.post("/api/pipeline/run",
                     json={"subject_id": first["subject"]["id"]}).json()
    _wait_for(pc, scoped["id"])

    # Only the GenAI note was processed.
    assert pc.get(
        "/api/pipeline/pending",
        params={"subject_id": first["subject"]["id"]},
    ).json()["unprocessed_blocks"] == 0
    assert pc.get(
        "/api/pipeline/pending", params={"subject_id": other["id"]},
    ).json()["unprocessed_blocks"] == 1

    concept_subjects = {
        row[0] for row in pipeline_app.query(
            "SELECT subject_id FROM concepts WHERE deleted_at IS NULL"
        )
    }
    assert concept_subjects == {first["subject"]["id"]}


def test_jobs_are_listed_newest_first(pc) -> None:
    _note(pc)
    first = pc.post("/api/pipeline/run", json={}).json()
    _wait_for(pc, first["id"])

    # A second note gives the second job something to do.
    pc.put(f"/api/notes/{_note(pc)['note']['id']}/blocks",
           json={"blocks": [{"id": None, "position": 0,
                             "block_type": "bullet_list_item",
                             "text": "Rerankers trade latency for precision"}]})
    second = pc.post("/api/pipeline/run", json={}).json()
    _wait_for(pc, second["id"])

    jobs = pc.get("/api/pipeline/jobs").json()
    assert [j["id"] for j in jobs][:2] == [second["id"], first["id"]]


def test_a_missing_job_is_a_404(pc) -> None:
    assert pc.get("/api/pipeline/jobs/9999").status_code == 404
    assert pc.post("/api/pipeline/jobs/9999/retry").status_code == 404


def test_a_succeeded_job_cannot_be_retried(pc) -> None:
    _note(pc)
    job = pc.post("/api/pipeline/run", json={}).json()
    _wait_for(pc, job["id"])

    response = pc.post(f"/api/pipeline/jobs/{job['id']}/retry")
    assert response.status_code == 409


def test_the_worker_survives_a_restart_with_a_queued_job(db_path: Path) -> None:
    """Spec §8.2 — the reason the worker is a daemon thread and not
    `BackgroundTasks`: "those die with the request and lose jobs on restart"."""
    # Start with the worker off so the job stays queued.
    first = start_app(db_path, extra_env={"RNL_LLM_PROVIDER": "mock",
                                          "RNL_NO_WORKER": "1"})
    try:
        with httpx.Client(base_url=first.base_url, timeout=60) as client:
            _note(client)
            job = client.post("/api/pipeline/run", json={}).json()
            time.sleep(1.0)
            # Still queued: nothing is running it.
            assert client.get(
                f"/api/pipeline/jobs/{job['id']}"
            ).json()["job"]["status"] == "queued"
    finally:
        first.stop()

    # Restart with the worker on. The job is picked up, not lost.
    second = start_app(db_path, extra_env={"RNL_LLM_PROVIDER": "mock"})
    try:
        with httpx.Client(base_url=second.base_url, timeout=60) as client:
            detail = _wait_for(client, job["id"])
            assert detail["job"]["status"] == "succeeded"
            assert detail["job"]["concepts_created"] >= 1
    finally:
        second.stop()
