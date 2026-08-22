"""MCQ generation and pool hygiene (spec §9.1, §11.2 **[LOCKED]**).

"Generation: eager, at pipeline time, via the Batch API (50% discount).
Generate 10 MCQs per concept covering `recall` and light `explain`."

Pool hygiene:
- "Retire an MCQ after `consecutive_correct >= 3`."
- "When a concept's active pool drops below 4, flag it for regeneration;
  regenerate on the next pipeline run, seeded with the retired stems so new
  ones differ."
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..llm import SchemaValidationError, get_provider, task_config
from ..llm.accounting import record_run
from ..models import MCQ, Concept
from ..prompts import load_prompt

log = logging.getLogger(__name__)

MCQ_PROMPT_VERSION = "mcq_generation_v1"

#: Spec §9.1
QUESTIONS_PER_CONCEPT = 10
RETIRE_AFTER_CONSECUTIVE_CORRECT = 3
REGENERATE_BELOW = 4


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Schema (spec §11.2)
# --------------------------------------------------------------------------

class MCQOption(BaseModel):
    id: str = Field(min_length=1, max_length=4)
    text: str = Field(min_length=1)


class GeneratedMCQ(BaseModel):
    stem: str = Field(min_length=1)
    options: list[MCQOption] = Field(min_length=4, max_length=4)
    correct_option_id: str
    explanation: str = Field(min_length=1)
    distractor_rationales: dict[str, str] = Field(default_factory=dict)
    dimension: str = "recall"
    difficulty: int = Field(ge=1, le=5, default=3)

    def is_coherent(self) -> bool:
        """Exactly one correct option, and it is one of the four offered."""
        ids = [o.id for o in self.options]
        return len(set(ids)) == 4 and self.correct_option_id in ids


class MCQBatch(BaseModel):
    questions: list[GeneratedMCQ] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Pool hygiene
# --------------------------------------------------------------------------

def active_pool(session: Session, concept_id: int) -> list[MCQ]:
    return list(session.exec(
        select(MCQ).where(
            MCQ.concept_id == concept_id,
            MCQ.status == "active",
            MCQ.deleted_at.is_(None),
        )
    ).all())


def retire_if_exhausted(session: Session, mcq: MCQ) -> bool:
    """Spec §9.1 — retire after three consecutive correct answers."""
    if mcq.status != "active":
        return False
    if mcq.consecutive_correct < RETIRE_AFTER_CONSECUTIVE_CORRECT:
        return False
    mcq.status = "retired"
    mcq.retired_at = _now()
    session.add(mcq)
    session.flush()
    return True


def needs_regeneration(session: Session, concept_id: int) -> bool:
    """"When a concept's active pool drops below 4, flag it for
    regeneration"."""
    return len(active_pool(session, concept_id)) < REGENERATE_BELOW


def retired_stems(session: Session, concept_id: int) -> list[str]:
    """Seed regeneration with what has already been asked, so new questions
    differ (§9.1)."""
    rows = session.exec(
        select(MCQ).where(
            MCQ.concept_id == concept_id,
            MCQ.status == "retired",
        )
    ).all()
    return [r.stem for r in rows]


def concepts_needing_mcqs(session: Session, concept_ids: set[int]) -> list[int]:
    """New concepts, plus any whose pool has fallen below the floor."""
    out: list[int] = []
    for concept_id in sorted(concept_ids):
        concept = session.get(Concept, concept_id)
        if concept is None or concept.deleted_at is not None:
            continue
        if needs_regeneration(session, concept_id):
            out.append(concept_id)
    return out


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------

def _render_request(concept: Concept, avoid: list[str]) -> str:
    lines = [
        f"CONCEPT: {concept.canonical_name}",
        f"DEFINITION: {concept.definition or ''}",
        f"DIFFICULTY: {concept.difficulty or 3}",
        f"COUNT: {QUESTIONS_PER_CONCEPT}",
    ]
    if avoid:
        lines.append("AVOID_STEMS:")
        lines.extend(f"- {stem}" for stem in avoid[:40])
    return "\n".join(lines)


def generate_for_concept(session: Session, concept: Concept,
                         job_id: int | None = None) -> int:
    """Generate a pool for one concept. Returns how many were stored."""
    provider = get_provider()
    cfg = task_config("mcq_generation")
    system = load_prompt(MCQ_PROMPT_VERSION)
    avoid = retired_stems(session, concept.id)

    try:
        result = provider.generate_structured(
            system_instruction=system,
            user_input=_render_request(concept, avoid),
            model=cfg["model"],
            schema=MCQBatch,
            thinking_level=cfg.get("thinking_level"),
            prompt_version=MCQ_PROMPT_VERSION,
        )
    except SchemaValidationError as exc:
        record_run(session, task="mcq_generation", job_id=job_id,
                   model=cfg["model"], prompt_version=MCQ_PROMPT_VERSION,
                   concept_id=concept.id, success=False,
                   error_text=exc.raw_response[:8000])
        raise
    except Exception as exc:
        record_run(session, task="mcq_generation", job_id=job_id,
                   model=cfg["model"], prompt_version=MCQ_PROMPT_VERSION,
                   concept_id=concept.id, success=False,
                   error_text=str(exc)[:8000])
        raise

    # §12.2 prices this task as batch. Record the mode that was actually used
    # so the cost is honest rather than aspirational.
    result.request_mode = getattr(provider, "batch_mode", "standard")
    record_run(session, task="mcq_generation", result=result, job_id=job_id,
               prompt_version=MCQ_PROMPT_VERSION, concept_id=concept.id)

    existing = {m.stem.strip().lower() for m in session.exec(
        select(MCQ).where(MCQ.concept_id == concept.id)
    ).all()}

    stored = 0
    for question in result.parsed.questions:
        if not question.is_coherent():
            log.warning("Dropping an incoherent MCQ for concept %s", concept.id)
            continue
        if question.stem.strip().lower() in existing:
            continue
        existing.add(question.stem.strip().lower())

        session.add(MCQ(
            concept_id=concept.id,
            dimension=question.dimension if question.dimension in ("recall", "explain")
            else "recall",
            stem=question.stem,
            options_json=json.dumps([o.model_dump() for o in question.options]),
            correct_option_id=question.correct_option_id,
            explanation=question.explanation,
            distractor_rationale_json=json.dumps(question.distractor_rationales),
            difficulty=float(question.difficulty),
            status="active",
            prompt_version=MCQ_PROMPT_VERSION,
            model=cfg["model"],
            job_id=job_id,
        ))
        stored += 1

    session.flush()
    return stored


def stage_generating_mcqs(session: Session, job, ctx) -> None:
    """Pipeline stage. A failure here does not fail the job: the concepts are
    already safely extracted, and MCQs can be regenerated on the next run."""
    targets = concepts_needing_mcqs(session, ctx.concept_ids)
    generated = 0

    for concept_id in targets:
        concept = session.get(Concept, concept_id)
        if concept is None:
            continue
        try:
            generated += generate_for_concept(session, concept, job_id=job.id)
        except Exception as exc:
            log.warning("MCQ generation failed for concept %s: %s",
                        concept_id, exc)

    job.mcqs_generated = generated
    session.add(job)
    session.flush()
