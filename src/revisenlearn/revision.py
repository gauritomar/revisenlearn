"""Revision — the prose loop (spec §9.2–§9.6 **[LOCKED]**).

"Prose review is the point of the app."

Generation is lazy: a question is written when its review item is served, with
the learner's recent failures and previously-seen wordings in the prompt.
Evaluation is a separate call returning booleans per key point; the rating is
then derived in Python, never by the model.

§9.6 shapes the surface: default session size 5, a session of one is a complete
session, the skip button is as prominent as submit, and nothing here frames a
backlog as a debt.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fsrs import Rating
from pydantic import BaseModel, Field
from sqlmodel import Session as DBSession
from sqlmodel import select

from .llm import get_provider, task_config
from .llm.accounting import record_run
from .models import (
    Concept,
    ConceptEdge,
    ConceptSource,
    Misconception,
    NoteBlock,
    Question,
    QuestionAttempt,
    ReviewItem,
    ReviewLog,
    Session as SessionRow,
    SessionItem,
)
from .prompts import load_prompt
from .scheduling import (
    Evaluation,
    NAME_BY_RATING,
    RATING_BY_NAME,
    apply_override,
    apply_retest,
    build_queue,
    derive_rating,
    due_items,
    record_review,
)

log = logging.getLogger(__name__)

QUESTION_PROMPT_VERSION = "question_generation_v1"
#: Spec §18 Phase 10 — "interview-specific prompt tuning". A separate
#: version rather than an edit, per §11: never edit a prompt in place.
INTERVIEW_PROMPT_VERSION = "question_generation_v2_interview"
EVALUATION_PROMPT_VERSION = "evaluation_v1"

#: Spec §9.6 — "Default revision session size is 5, not 10. Starting is the
#: hard part; make the smallest unit genuinely small."
DEFAULT_SESSION_SIZE = 5
SESSION_SIZES = (5, 10, 20)

#: Spec §9.2 — "State the expected length under the question as a hint, not a
#: limit."
EXPECTED_LENGTH = {
    "recall": "2–4 sentences",
    "explain": "2–4 sentences",
    "apply": "a paragraph or two",
    "debug": "a paragraph or two",
    "synthesis": "a paragraph or two",
    "interview": "a paragraph or two",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Schemas (spec §11.3, §11.4)
# --------------------------------------------------------------------------

class GeneratedQuestion(BaseModel):
    question_text: str = Field(min_length=1)
    expected_answer: str = Field(min_length=1)
    #: §11.3 — "3 to 6 independently checkable claims".
    key_points: list[str] = Field(min_length=3, max_length=6)
    common_misconceptions: list[str] = Field(default_factory=list)
    difficulty: int = Field(ge=1, le=5, default=3)


class KeyPointHit(BaseModel):
    point: str
    hit: bool


class EvaluationResult(BaseModel):
    key_point_hits: list[KeyPointHit] = Field(default_factory=list)
    factually_incorrect_claims: list[str] = Field(default_factory=list)
    misconceptions: list[str] = Field(default_factory=list)
    feedback: str = ""
    #: Stored for comparison, deliberately not used (§9.3).
    suggested_rating: str | None = None


# --------------------------------------------------------------------------
# Dashboard (spec §9.2, §9.6)
# --------------------------------------------------------------------------

def dashboard(session: DBSession, now: datetime | None = None) -> dict:
    """Spec §9.2 — "due count in neutral grey, weak areas, history".

    §9.6: the count is information, never a debt. Nothing here returns a
    severity, a colour, or an "overdue!" flag for the UI to escalate.
    """
    now = now or _now()
    items = due_items(session, now)
    overdue = sum(
        1 for i in items
        if i.due_at is not None
        and (i.due_at if i.due_at.tzinfo else i.due_at.replace(tzinfo=timezone.utc)) < now
    )

    logs = session.exec(
        select(ReviewLog).order_by(ReviewLog.created_at.desc()).limit(200)
    ).all()

    weak: list[dict] = []
    seen: set[int] = set()
    for row in logs:
        if row.rating is None or row.rating > int(Rating.Hard):
            continue
        if row.review_item_id in seen:
            continue
        seen.add(row.review_item_id)
        concept = session.get(Concept, row.concept_id)
        weak.append({
            "concept_id": row.concept_id,
            "concept_name": concept.canonical_name if concept else "(deleted)",
            "dimension": row.dimension,
            "last_rating": NAME_BY_RATING.get(Rating(row.rating), "?"),
        })
        if len(weak) >= 8:
            break

    return {
        "due_count": len(items),
        "overdue_count": overdue,
        "new_count": sum(1 for i in items if i.reps == 0),
        "reviews_logged": len(session.exec(select(ReviewLog)).all()),
        "weak_areas": weak,
        "sizes": list(SESSION_SIZES),
        "default_size": DEFAULT_SESSION_SIZE,
    }


# --------------------------------------------------------------------------
# Lazy question generation (spec §9.2, §11.3)
# --------------------------------------------------------------------------

def _source_text(session: DBSession, concept_id: int, limit: int = 6) -> str:
    sources = session.exec(
        select(ConceptSource).where(
            ConceptSource.concept_id == concept_id,
            ConceptSource.invalidated_at.is_(None),
        ).limit(limit)
    ).all()
    texts = []
    for source in sources:
        block = session.get(NoteBlock, source.note_block_id)
        if block and block.deleted_at is None and (block.text or "").strip():
            texts.append(block.text.strip())
    return "\n".join(f"- {t}" for t in texts)


def _neighbours(session: DBSession, concept_id: int) -> tuple[list[str], list[str]]:
    edges = session.exec(
        select(ConceptEdge).where(
            ConceptEdge.status == "accepted",
            ConceptEdge.deleted_at.is_(None),
        )
    ).all()
    prerequisites, related = [], []
    for edge in edges:
        if edge.target_concept_id == concept_id and edge.relation_type == "prerequisite_of":
            other = session.get(Concept, edge.source_concept_id)
            if other:
                prerequisites.append(other.canonical_name)
        elif concept_id in (edge.source_concept_id, edge.target_concept_id):
            other_id = (edge.target_concept_id if edge.source_concept_id == concept_id
                        else edge.source_concept_id)
            other = session.get(Concept, other_id)
            if other:
                related.append(other.canonical_name)
    return prerequisites, related


def _recent_attempts(session: DBSession, item: ReviewItem, limit: int = 5) -> list[dict]:
    logs = session.exec(
        select(ReviewLog)
        .where(ReviewLog.review_item_id == item.id)
        .order_by(ReviewLog.created_at.desc())
        .limit(limit)
    ).all()
    out = []
    for row in logs:
        missed: list[str] = []
        if row.evaluator_json:
            try:
                payload = json.loads(row.evaluator_json)
                missed = [p["point"] for p in payload.get("key_point_hits", [])
                          if not p.get("hit")]
            except (json.JSONDecodeError, KeyError, TypeError):
                missed = []
        question = session.get(Question, row.question_id) if row.question_id else None
        out.append({
            "question": question.question_text if question else "",
            "rating": NAME_BY_RATING.get(Rating(row.rating), "?") if row.rating else "?",
            "missed_points": missed,
        })
    return out


def _open_misconceptions(session: DBSession, concept_id: int) -> list[str]:
    rows = session.exec(
        select(Misconception).where(
            Misconception.concept_id == concept_id,
            Misconception.resolved_at.is_(None),
        )
    ).all()
    return [r.text for r in rows]


def _previous_stems(session: DBSession, concept_id: int, dimension: str,
                    limit: int = 8) -> list[str]:
    rows = session.exec(
        select(Question)
        .where(Question.concept_id == concept_id,
               Question.dimension == dimension,
               Question.deleted_at.is_(None))
        .order_by(Question.created_at.desc())
        .limit(limit)
    ).all()
    return [r.question_text for r in rows]


def build_generation_input(session: DBSession, item: ReviewItem,
                           rephrase: bool = False) -> str:
    """Spec §11.3's inputs. §12.4: "Send only the relevant note chunk and the
    concept's own history … never whole notes.\""""
    concept = session.get(Concept, item.concept_id)
    prerequisites, related = _neighbours(session, item.concept_id)
    attempts = _recent_attempts(session, item)
    misconceptions = _open_misconceptions(session, item.concept_id)
    stems = _previous_stems(session, item.concept_id, item.dimension)

    lines = [
        f"CONCEPT: {concept.canonical_name if concept else ''}",
        f"DEFINITION: {concept.definition if concept else ''}",
        f"DIMENSION: {item.dimension}",
        f"TARGET_DIFFICULTY: {concept.difficulty if concept else 3}",
        "",
        "SOURCE_NOTES:",
        _source_text(session, item.concept_id) or "(none recorded)",
    ]
    if prerequisites:
        lines += ["", "PREREQUISITES: " + ", ".join(sorted(set(prerequisites)))]
    if related:
        lines += ["RELATED_CONCEPTS: " + ", ".join(sorted(set(related))[:8])]
    if attempts:
        lines += ["", "LAST_ATTEMPTS:"]
        for attempt in attempts:
            missed = ("; missed: " + ", ".join(attempt["missed_points"])
                      if attempt["missed_points"] else "")
            lines.append(f"- [{attempt['rating']}] {attempt['question'][:160]}{missed}")
    if misconceptions:
        lines += ["", "OPEN_MISCONCEPTIONS:"] + [f"- {m}" for m in misconceptions]
    if stems:
        lines += ["", "PREVIOUS_STEMS:"] + [f"- {s[:160]}" for s in stems]
    if rephrase:
        lines += ["", "This is a REPHRASE: same concept and dimension, a "
                      "different context and framing from every previous stem."]
    return "\n".join(lines)


def generate_question(session: DBSession, item: ReviewItem,
                      reason: str = "due",
                      session_id: int | None = None) -> Question:
    """One question, written now (spec §9.2 — generation is lazy)."""
    provider = get_provider()
    cfg = task_config("question_generation")
    # The interview dimension wants a different framing entirely, so it gets
    # its own prompt version and that version is recorded on the artefact.
    version = (INTERVIEW_PROMPT_VERSION if item.dimension == "interview"
               else QUESTION_PROMPT_VERSION)
    system = load_prompt(version)

    try:
        result = provider.generate_structured(
            system_instruction=system,
            user_input=build_generation_input(
                session, item, rephrase=reason == "retest_rephrased"
            ),
            model=cfg["model"],
            schema=GeneratedQuestion,
            thinking_level=cfg.get("thinking_level"),
            prompt_version=version,
        )
    except Exception as exc:
        record_run(session, task="question_generation", session_id=session_id,
                   model=cfg["model"], prompt_version=version,
                   concept_id=item.concept_id, success=False,
                   error_text=str(exc)[:8000])
        raise

    record_run(session, task="question_generation", result=result,
               session_id=session_id, prompt_version=version,
               concept_id=item.concept_id)

    parsed: GeneratedQuestion = result.parsed
    source_ids = [
        s.note_id for s in session.exec(
            select(ConceptSource).where(
                ConceptSource.concept_id == item.concept_id,
                ConceptSource.invalidated_at.is_(None),
            )
        ).all()
    ]

    question = Question(
        concept_id=item.concept_id,
        review_item_id=item.id,
        dimension=item.dimension,
        question_text=parsed.question_text,
        expected_answer=parsed.expected_answer,
        key_points_json=json.dumps(parsed.key_points),
        common_misconceptions_json=json.dumps(parsed.common_misconceptions),
        difficulty=float(parsed.difficulty),
        source_note_ids_json=json.dumps(sorted(set(source_ids))),
        generation_reason=reason,
        prompt_version=version,
        model=cfg["model"],
    )
    session.add(question)
    session.flush()
    return question


# --------------------------------------------------------------------------
# Evaluation (spec §9.3, §11.4)
# --------------------------------------------------------------------------

def evaluate_answer(session: DBSession, question: Question, answer_text: str,
                    session_id: int | None = None) -> Evaluation:
    provider = get_provider()
    cfg = task_config("evaluation")
    system = load_prompt(EVALUATION_PROMPT_VERSION)

    key_points = json.loads(question.key_points_json or "[]")
    user_input = "\n".join([
        f"QUESTION: {question.question_text}",
        f"EXPECTED_ANSWER: {question.expected_answer}",
        "KEY_POINTS:",
        *[f"- {p}" for p in key_points],
        "",
        "LEARNER_ANSWER:",
        answer_text,
    ])

    try:
        result = provider.generate_structured(
            system_instruction=system,
            user_input=user_input,
            model=cfg["model"],
            schema=EvaluationResult,
            thinking_level=cfg.get("thinking_level"),
            prompt_version=EVALUATION_PROMPT_VERSION,
        )
    except Exception as exc:
        record_run(session, task="evaluation", session_id=session_id,
                   model=cfg["model"], prompt_version=EVALUATION_PROMPT_VERSION,
                   concept_id=question.concept_id, success=False,
                   error_text=str(exc)[:8000])
        raise

    record_run(session, task="evaluation", result=result, session_id=session_id,
               prompt_version=EVALUATION_PROMPT_VERSION,
               concept_id=question.concept_id)

    parsed: EvaluationResult = result.parsed
    return Evaluation(
        key_point_hits=[p.model_dump() for p in parsed.key_point_hits],
        factually_incorrect_claims=list(parsed.factually_incorrect_claims),
        misconceptions=list(parsed.misconceptions),
        feedback=parsed.feedback,
        suggested_rating=parsed.suggested_rating,
    )


def _record_misconceptions(session: DBSession, concept_id: int,
                           texts: list[str]) -> None:
    for text in texts:
        cleaned = (text or "").strip()
        if not cleaned:
            continue
        existing = session.exec(
            select(Misconception).where(
                Misconception.concept_id == concept_id,
                Misconception.text == cleaned,
            )
        ).first()
        if existing is None:
            session.add(Misconception(concept_id=concept_id, text=cleaned))
        else:
            existing.times_seen += 1
            existing.last_seen_at = _now()
            session.add(existing)
    session.flush()


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------

def create_session(session: DBSession, count: int = DEFAULT_SESSION_SIZE,
                   subject_ids: tuple[int, ...] = ()) -> SessionRow:
    items = build_queue(session, count, subject_ids=subject_ids)

    row = SessionRow(
        session_type="revision",
        scope_json=json.dumps({"subject_ids": list(subject_ids)}),
        planned_count=len(items),
        started_at=_now(),
    )
    session.add(row)
    session.flush()

    for position, item in enumerate(items):
        session.add(SessionItem(
            session_id=row.id,
            position=position,
            item_type="question",
            review_item_id=item.id,
            selection_bucket="new" if item.reps == 0 else "due",
        ))
    session.flush()
    return row


def next_item(session: DBSession, session_id: int) -> SessionItem | None:
    return session.exec(
        select(SessionItem)
        .where(SessionItem.session_id == session_id,
               SessionItem.answered_at.is_(None))
        .order_by(SessionItem.position)
    ).first()


def serve(session: DBSession, item: SessionItem) -> dict:
    """Generate the question now and hand it over (§9.2 — lazy)."""
    review_item = session.get(ReviewItem, item.review_item_id)
    if review_item is None:
        raise LookupError("Review item missing")

    if item.question_id is None:
        question = generate_question(session, review_item,
                                     session_id=item.session_id)
        item.question_id = question.id
        item.served_at = _now()
        session.add(item)
        session.flush()
    else:
        question = session.get(Question, item.question_id)

    concept = session.get(Concept, review_item.concept_id)
    return {
        "item_id": item.id,
        "position": item.position,
        "question_id": question.id,
        "concept_id": review_item.concept_id,
        "concept_name": concept.canonical_name if concept else "",
        "dimension": review_item.dimension,
        "question_text": question.question_text,
        "expected_length": EXPECTED_LENGTH.get(review_item.dimension,
                                               "a paragraph or two"),
        "selection_bucket": item.selection_bucket,
    }


def answer(session: DBSession, session_id: int, item_id: int,
           answer_text: str, response_ms: int | None = None) -> dict:
    """Evaluate, derive the rating, advance FSRS, append to `review_logs`."""
    item = session.get(SessionItem, item_id)
    if item is None or item.session_id != session_id:
        raise LookupError("Session item not found")
    if item.answered_at is not None:
        raise ValueError("That question has already been answered")

    question = session.get(Question, item.question_id)
    review_item = session.get(ReviewItem, item.review_item_id)
    if question is None or review_item is None:
        raise LookupError("Question or review item missing")

    evaluation = evaluate_answer(session, question, answer_text,
                                 session_id=session_id)
    evaluator_rating = derive_rating(evaluation)

    attempt = QuestionAttempt(
        question_id=question.id,
        review_item_id=review_item.id,
        session_id=session_id,
        user_answer=answer_text,
        is_retest=False,
        evaluator_json=json.dumps({
            "key_point_hits": evaluation.key_point_hits,
            "factually_incorrect_claims": evaluation.factually_incorrect_claims,
            "misconceptions": evaluation.misconceptions,
            "feedback": evaluation.feedback,
            "suggested_rating": evaluation.suggested_rating,
        }),
        evaluator_rating=int(evaluator_rating),
        final_rating=int(evaluator_rating),
        response_ms=response_ms,
    )
    session.add(attempt)
    session.flush()

    log_row = record_review(
        session, review_item,
        final_rating=evaluator_rating,
        evaluator_rating=evaluator_rating,
        evaluation=evaluation,
        question_id=question.id,
        question_attempt_id=attempt.id,
        response_ms=response_ms,
    )
    _record_misconceptions(session, review_item.concept_id,
                           evaluation.misconceptions)

    item.answered_at = _now()
    session.add(item)

    row = session.get(SessionRow, session_id)
    if row is not None:
        row.completed_count += 1
        if evaluator_rating in (Rating.Good, Rating.Easy):
            row.correct_count += 1
        session.add(row)
    session.flush()

    return _feedback_payload(session, question, attempt, evaluation,
                             evaluator_rating, log_row)


def skip(session: DBSession, session_id: int, item_id: int) -> dict:
    """Spec §9.2 — "Skip / I don't know" logs `rating = Again`, shows the
    expected answer and key points, and moves on. No penalty framing."""
    item = session.get(SessionItem, item_id)
    if item is None or item.session_id != session_id:
        raise LookupError("Session item not found")
    if item.answered_at is not None:
        raise ValueError("That question has already been answered")

    question = session.get(Question, item.question_id)
    review_item = session.get(ReviewItem, item.review_item_id)
    if question is None or review_item is None:
        raise LookupError("Question or review item missing")

    evaluation = Evaluation(
        key_point_hits=[{"point": p, "hit": False}
                        for p in json.loads(question.key_points_json or "[]")],
        factually_incorrect_claims=[],
        misconceptions=[],
        feedback="Skipped. The expected answer and key points are below.",
        suggested_rating=None,
    )

    attempt = QuestionAttempt(
        question_id=question.id,
        review_item_id=review_item.id,
        session_id=session_id,
        user_answer=None,
        evaluator_rating=int(Rating.Again),
        final_rating=int(Rating.Again),
    )
    session.add(attempt)
    session.flush()

    log_row = record_review(
        session, review_item,
        final_rating=Rating.Again,
        evaluator_rating=Rating.Again,
        evaluation=evaluation,
        question_id=question.id,
        question_attempt_id=attempt.id,
    )

    item.answered_at = _now()
    session.add(item)
    row = session.get(SessionRow, session_id)
    if row is not None:
        row.completed_count += 1
        session.add(row)
    session.flush()

    payload = _feedback_payload(session, question, attempt, evaluation,
                                Rating.Again, log_row)
    payload["skipped"] = True
    return payload


def _feedback_payload(session: DBSession, question: Question,
                      attempt: QuestionAttempt, evaluation: Evaluation,
                      rating: Rating, log_row: ReviewLog) -> dict:
    review_item = session.get(ReviewItem, attempt.review_item_id)
    return {
        "attempt_id": attempt.id,
        "question_id": question.id,
        "rating": NAME_BY_RATING[rating],
        "hit_ratio": round(evaluation.hit_ratio, 4),
        "key_point_hits": evaluation.key_point_hits,
        "factually_incorrect_claims": evaluation.factually_incorrect_claims,
        "misconceptions": evaluation.misconceptions,
        "feedback": evaluation.feedback,
        "expected_answer": question.expected_answer,
        "suggested_rating": evaluation.suggested_rating,
        "due_at": review_item.due_at.isoformat() if review_item and review_item.due_at else None,
        "skipped": False,
        "log_id": log_row.id,
    }


def override(session: DBSession, session_id: int, attempt_id: int,
             direction: str) -> dict:
    """Spec §9.4 **[LOCKED]** — the escape hatch, usable freely.

    The original evaluator rating is preserved; FSRS is re-run from the state
    *before* this attempt so the override replaces it rather than compounding
    on top of it.
    """
    attempt = session.get(QuestionAttempt, attempt_id)
    if attempt is None or attempt.session_id != session_id:
        raise LookupError("Attempt not found")

    review_item = session.get(ReviewItem, attempt.review_item_id)
    if review_item is None:
        raise LookupError("Review item missing")

    evaluator_rating = Rating(attempt.evaluator_rating)
    new_rating = apply_override(evaluator_rating, direction)
    if new_rating == Rating(attempt.final_rating):
        return {"rating": NAME_BY_RATING[new_rating], "changed": False}

    original = session.exec(
        select(ReviewLog)
        .where(ReviewLog.question_attempt_id == attempt.id)
        .order_by(ReviewLog.created_at)
    ).first()
    if original is None:
        raise LookupError("No review log for that attempt")

    # Rewind to the state this attempt started from. The original log row is
    # never touched — §6 makes review_logs append-only — so the correction is
    # itself a new row.
    review_item.fsrs_stability = original.stability_before
    review_item.fsrs_difficulty = original.difficulty_before
    review_item.due_at = original.due_before
    review_item.reps = max(0, review_item.reps - 1)
    if Rating(original.rating) is Rating.Again:
        review_item.lapses = max(0, review_item.lapses - 1)
    session.add(review_item)
    session.flush()

    evaluation = None
    if original.evaluator_json:
        try:
            payload = json.loads(original.evaluator_json)
            evaluation = Evaluation(
                key_point_hits=payload.get("key_point_hits", []),
                factually_incorrect_claims=payload.get(
                    "factually_incorrect_claims", []),
                misconceptions=payload.get("misconceptions", []),
                feedback=payload.get("feedback", ""),
                suggested_rating=payload.get("suggested_rating"),
            )
        except json.JSONDecodeError:
            evaluation = None

    record_review(
        session, review_item,
        final_rating=new_rating,
        evaluator_rating=evaluator_rating,
        user_override_rating=new_rating,
        evaluation=evaluation,
        question_id=attempt.question_id,
        question_attempt_id=attempt.id,
    )

    attempt.user_override_rating = int(new_rating)
    attempt.final_rating = int(new_rating)
    session.add(attempt)
    session.flush()

    return {
        "rating": NAME_BY_RATING[new_rating],
        "changed": True,
        "due_at": review_item.due_at.isoformat() if review_item.due_at else None,
    }


# --------------------------------------------------------------------------
# §9.5 Immediate retest
# --------------------------------------------------------------------------

def retest_offers(session: DBSession, session_id: int) -> list[dict]:
    """"any item rated `Again` or `Hard` is offered for immediate retest"."""
    attempts = session.exec(
        select(QuestionAttempt).where(QuestionAttempt.session_id == session_id,
                                      QuestionAttempt.is_retest == False)  # noqa: E712
    ).all()
    offers = []
    for attempt in attempts:
        if attempt.final_rating is None:
            continue
        if Rating(attempt.final_rating) not in (Rating.Again, Rating.Hard):
            continue
        question = session.get(Question, attempt.question_id)
        review_item = session.get(ReviewItem, attempt.review_item_id)
        concept = session.get(Concept, review_item.concept_id) if review_item else None
        offers.append({
            "attempt_id": attempt.id,
            "question_id": attempt.question_id,
            "concept_name": concept.canonical_name if concept else "",
            "dimension": review_item.dimension if review_item else "",
            "rating": NAME_BY_RATING[Rating(attempt.final_rating)],
            "question_text": question.question_text if question else "",
        })
    return offers


def start_retest(session: DBSession, session_id: int, attempt_id: int,
                 mode: str) -> dict:
    """`mode` is `same` (identical wording) or `rephrased` (fresh generation)."""
    if mode not in ("same", "rephrased"):
        raise ValueError("mode must be 'same' or 'rephrased'")

    original = session.get(QuestionAttempt, attempt_id)
    if original is None or original.session_id != session_id:
        raise LookupError("Attempt not found")
    review_item = session.get(ReviewItem, original.review_item_id)
    if review_item is None:
        raise LookupError("Review item missing")

    if mode == "same":
        question = session.get(Question, original.question_id)
    else:
        question = generate_question(session, review_item,
                                     reason="retest_rephrased",
                                     session_id=session_id)

    concept = session.get(Concept, review_item.concept_id)
    return {
        "retest_of_attempt_id": attempt_id,
        "question_id": question.id,
        "mode": mode,
        "concept_name": concept.canonical_name if concept else "",
        "dimension": review_item.dimension,
        "question_text": question.question_text,
        "expected_length": EXPECTED_LENGTH.get(review_item.dimension,
                                               "a paragraph or two"),
    }


def answer_retest(session: DBSession, session_id: int, question_id: int,
                  retest_of_attempt_id: int, answer_text: str,
                  response_ms: int | None = None) -> dict:
    """Spec §9.5 **[LOCKED]** — the first attempt stays authoritative.

    A retest may advance a relearning step, but can never upgrade the original
    rating or push the due date further out. Otherwise the retest teaches FSRS
    the user knew something they did not.
    """
    question = session.get(Question, question_id)
    original = session.get(QuestionAttempt, retest_of_attempt_id)
    if question is None or original is None:
        raise LookupError("Question or original attempt missing")
    review_item = session.get(ReviewItem, original.review_item_id)
    if review_item is None:
        raise LookupError("Review item missing")

    evaluation = evaluate_answer(session, question, answer_text,
                                 session_id=session_id)
    rating = derive_rating(evaluation)

    attempt = QuestionAttempt(
        question_id=question.id,
        review_item_id=review_item.id,
        session_id=session_id,
        user_answer=answer_text,
        is_retest=True,
        retest_of_attempt_id=retest_of_attempt_id,
        evaluator_json=json.dumps({
            "key_point_hits": evaluation.key_point_hits,
            "factually_incorrect_claims": evaluation.factually_incorrect_claims,
            "misconceptions": evaluation.misconceptions,
            "feedback": evaluation.feedback,
            "suggested_rating": evaluation.suggested_rating,
        }),
        evaluator_rating=int(rating),
        final_rating=int(rating),
        response_ms=response_ms,
    )
    session.add(attempt)
    session.flush()

    due_before = review_item.due_at
    advanced = apply_retest(session, review_item, rating)

    # The retest is logged either way — §6 wants the whole history — but it is
    # logged as a retest, and FSRS state only moved if apply_retest allowed it.
    row = ReviewLog(
        review_item_id=review_item.id,
        concept_id=review_item.concept_id,
        dimension=review_item.dimension,
        question_id=question.id,
        question_attempt_id=attempt.id,
        rating=int(rating),
        evaluator_rating=int(rating),
        evaluator_json=attempt.evaluator_json,
        response_ms=response_ms,
        due_before=due_before,
        due_after=review_item.due_at,
        stability_before=review_item.fsrs_stability,
        stability_after=review_item.fsrs_stability,
        difficulty_before=review_item.fsrs_difficulty,
        difficulty_after=review_item.fsrs_difficulty,
        is_retest=True,
        created_at=_now(),
    )
    session.add(row)
    session.flush()

    payload = _feedback_payload(session, question, attempt, evaluation,
                                rating, row)
    payload["is_retest"] = True
    payload["relearning_step_advanced"] = advanced
    return payload


# --------------------------------------------------------------------------
# Finishing
# --------------------------------------------------------------------------

def finish(session: DBSession, session_id: int) -> dict:
    """Spec §9.6 — "A session of one is a complete session." Ending early
    records it as finished, not abandoned."""
    row = session.get(SessionRow, session_id)
    if row is None:
        raise LookupError("Session not found")
    if row.finished_at is None:
        row.finished_at = _now()
        started = row.started_at
        if started is not None:
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            row.duration_ms = int(
                (row.finished_at - started).total_seconds() * 1000
            )
        session.add(row)
        session.flush()
    return summary(session, session_id)


def summary(session: DBSession, session_id: int) -> dict:
    row = session.get(SessionRow, session_id)
    if row is None:
        raise LookupError("Session not found")

    attempts = session.exec(
        select(QuestionAttempt)
        .where(QuestionAttempt.session_id == session_id,
               QuestionAttempt.is_retest == False)  # noqa: E712
    ).all()

    per_concept: dict[int, dict] = {}
    for attempt in attempts:
        review_item = session.get(ReviewItem, attempt.review_item_id)
        if review_item is None:
            continue
        concept = session.get(Concept, review_item.concept_id)
        entry = per_concept.setdefault(review_item.concept_id, {
            "concept_id": review_item.concept_id,
            "concept_name": concept.canonical_name if concept else "(deleted)",
            "answered": 0,
            "ratings": [],
        })
        entry["answered"] += 1
        if attempt.final_rating:
            entry["ratings"].append(NAME_BY_RATING[Rating(attempt.final_rating)])

    return {
        "session_id": session_id,
        "planned_count": row.planned_count,
        "completed_count": row.completed_count,
        # §9.6 — say what was done, not what was left.
        "answered": len(attempts),
        "duration_ms": row.duration_ms,
        "finished": row.finished_at is not None,
        "per_concept": list(per_concept.values()),
        "retest_offers": retest_offers(session, session_id),
    }


# --------------------------------------------------------------------------
# Phase 10 — Interview mode (spec §10.1, §18)
# --------------------------------------------------------------------------

MOCK_ROUND_SIZE = 5


def mock_round(session: DBSession, count: int = MOCK_ROUND_SIZE,
               subject_ids: tuple[int, ...] = ()) -> SessionRow:
    """Spec §18 Phase 10 — "a 'mock round' session type that serves 5 interview
    questions across related concepts".

    "Across related concepts" is the point: a mock round should feel like one
    interview about a connected area, not five unrelated questions. The round
    is seeded with the highest-priority interview item, then walks its accepted
    edges outward, falling back to priority order if the neighbourhood is
    smaller than the round.
    """
    from .graph import neighbours_within
    from .models import Concept as ConceptModel
    from .scheduling import interview_mode_on, priority

    if not interview_mode_on(session):
        raise ValueError(
            "Interview mode is off. Turn it on in Settings; it unsuspends "
            "your interview review items."
        )

    candidates = [
        item for item in due_items(session, subject_ids=subject_ids)
        if item.dimension == "interview"
    ]
    if not candidates:
        raise LookupError("No interview items are ready yet")

    candidates.sort(key=lambda i: -priority(session, i))
    seed = candidates[0]
    near = neighbours_within(session, seed.concept_id, hops=2)

    chosen: list[ReviewItem] = [seed]
    seen_concepts = {seed.concept_id}
    for item in candidates[1:]:
        if len(chosen) >= count:
            break
        if item.concept_id in near and item.concept_id not in seen_concepts:
            chosen.append(item)
            seen_concepts.add(item.concept_id)
    # Short neighbourhood: fill by priority so the round is still full.
    for item in candidates[1:]:
        if len(chosen) >= count:
            break
        if item.concept_id not in seen_concepts:
            chosen.append(item)
            seen_concepts.add(item.concept_id)

    row = SessionRow(
        session_type="revision",
        scope_json=json.dumps({"subject_ids": list(subject_ids),
                               "mock_round": True,
                               "seed_concept_id": seed.concept_id}),
        planned_count=len(chosen),
        started_at=_now(),
    )
    session.add(row)
    session.flush()

    for position, item in enumerate(chosen):
        session.add(SessionItem(
            session_id=row.id,
            position=position,
            item_type="question",
            review_item_id=item.id,
            selection_bucket="due" if item.reps else "new",
        ))
    session.flush()

    concept = session.get(ConceptModel, seed.concept_id)
    log.info("Mock round of %s seeded from %s", len(chosen),
             concept.canonical_name if concept else seed.concept_id)
    return row
