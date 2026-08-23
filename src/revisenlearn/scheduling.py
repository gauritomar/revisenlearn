"""FSRS scheduling, priority and mastery (spec §10 **[LOCKED]**).

"Use `py-fsrs` with defaults. Do not reimplement FSRS."

This module owns the translation between the library's `Card` and our
`review_items` row, the §10.4 priority formula, and the §10.5 mastery formula.
`review_logs` is append-only: written here, never updated, never deleted.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fsrs import Card, Rating, Scheduler, State
from sqlmodel import Session, select

from .models import (
    Concept,
    QuestionAttempt,
    ReviewItem,
    ReviewLog,
    Setting,
)

log = logging.getLogger(__name__)

FSRS_SETTINGS_KEY = "fsrs"
PRIORITY_SETTINGS_KEY = "priority_weights"
INTERVIEW_MODE_KEY = "interview_mode"

#: Spec §10.3
DEFAULT_FSRS = {
    "desired_retention": 0.90,
    "maximum_interval": 365,
    "enable_fuzz": True,
    "learning_steps": ["1m", "10m"],
    "relearning_steps": ["10m"],
}

#: Spec §10.4
DEFAULT_WEIGHTS = {
    "w_overdue": 0.5,
    "w_lapse": 0.3,
    "w_gap": 0.4,
    "w_interview": 0.3,
}

RATING_BY_NAME = {
    "again": Rating.Again,
    "hard": Rating.Hard,
    "good": Rating.Good,
    "easy": Rating.Easy,
}
NAME_BY_RATING = {v: k for k, v in RATING_BY_NAME.items()}
#: Ordered worst → best, which is what the §9.4 override steps along.
RATING_ORDER = [Rating.Again, Rating.Hard, Rating.Good, Rating.Easy]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; FSRS requires aware ones."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def parse_step(text: str) -> timedelta:
    """`"1m"`, `"10m"`, `"1h"`, `"1d"` → timedelta."""
    text = text.strip().lower()
    unit = text[-1]
    amount = float(text[:-1])
    return {
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
    }[unit]


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def _read_setting(session: Session, key: str, default: dict) -> dict:
    row = session.get(Setting, key)
    if row is None:
        return dict(default)
    try:
        value = json.loads(row.value_json)
    except json.JSONDecodeError:
        return dict(default)
    if not isinstance(value, dict):
        return dict(default)
    return {**default, **value}


def load_scheduler(session: Session) -> Scheduler:
    """Spec §10.3 — config lives in `settings`, so it is tunable without a
    code change."""
    cfg = _read_setting(session, FSRS_SETTINGS_KEY, DEFAULT_FSRS)
    return Scheduler(
        desired_retention=float(cfg["desired_retention"]),
        maximum_interval=int(cfg["maximum_interval"]),
        enable_fuzzing=bool(cfg["enable_fuzz"]),
        learning_steps=[parse_step(s) for s in cfg["learning_steps"]],
        relearning_steps=[parse_step(s) for s in cfg["relearning_steps"]],
    )


def load_weights(session: Session) -> dict:
    return _read_setting(session, PRIORITY_SETTINGS_KEY, DEFAULT_WEIGHTS)


def interview_mode_on(session: Session) -> bool:
    """Spec §10.1 — "A single Settings toggle, Interview mode, unsuspends them
    all. Default off.\""""
    row = session.get(Setting, INTERVIEW_MODE_KEY)
    if row is None:
        return False
    try:
        return bool(json.loads(row.value_json))
    except json.JSONDecodeError:
        return False


# --------------------------------------------------------------------------
# ReviewItem <-> Card
# --------------------------------------------------------------------------

def to_card(item: ReviewItem) -> Card:
    """A never-reviewed item becomes a fresh Card."""
    if item.fsrs_state is None or item.due_at is None:
        return Card()
    return Card(
        card_id=item.id,
        state=State(int(item.fsrs_state)),
        step=item.fsrs_step,
        stability=item.fsrs_stability,
        difficulty=item.fsrs_difficulty,
        due=_aware(item.due_at),
        last_review=_aware(item.last_reviewed_at),
    )


def apply_card(item: ReviewItem, card: Card) -> None:
    item.fsrs_state = str(int(card.state))
    item.fsrs_step = card.step
    item.fsrs_stability = card.stability
    item.fsrs_difficulty = card.difficulty
    item.due_at = card.due
    item.last_reviewed_at = card.last_review
    item.updated_at = _now()


def retrievability(session: Session, item: ReviewItem,
                   now: datetime | None = None) -> float:
    """0..1. A never-reviewed item has no retention to lose, so it reads 0."""
    if item.fsrs_state is None or item.due_at is None:
        return 0.0
    scheduler = load_scheduler(session)
    return float(scheduler.get_card_retrievability(to_card(item), now or _now()))


# --------------------------------------------------------------------------
# §9.3 Deterministic rating
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Evaluation:
    """The §9.3 evaluator output, already parsed."""

    key_point_hits: list[dict]
    factually_incorrect_claims: list[str]
    misconceptions: list[str]
    feedback: str
    suggested_rating: str | None = None

    @property
    def hit_ratio(self) -> float:
        if not self.key_point_hits:
            return 0.0
        hits = sum(1 for p in self.key_point_hits if p.get("hit"))
        return hits / len(self.key_point_hits)


def derive_rating(evaluation: Evaluation) -> Rating:
    """Spec §9.3 **[LOCKED]** — derived in Python, never by the model.

    `suggested_rating` is stored for comparison but deliberately not used: if
    the two disagree often, that is useful signal.
    """
    ratio = evaluation.hit_ratio
    if (evaluation.factually_incorrect_claims
            or evaluation.misconceptions
            or ratio < 0.4):
        return Rating.Again
    if ratio < 0.7:
        return Rating.Hard
    if ratio < 0.95:
        return Rating.Good
    return Rating.Easy


def apply_override(rating: Rating, override: str | None) -> Rating:
    """Spec §9.4 **[LOCKED]**.

    "I actually got this" → one step up. "No, I was wrong" → Again.
    """
    if override is None:
        return rating
    if override == "wrong":
        return Rating.Again
    if override == "got_it":
        index = RATING_ORDER.index(rating)
        return RATING_ORDER[min(index + 1, len(RATING_ORDER) - 1)]
    raise ValueError(f"Unknown override {override!r}")


# --------------------------------------------------------------------------
# Recording a review
# --------------------------------------------------------------------------

def record_review(
    session: Session,
    item: ReviewItem,
    *,
    final_rating: Rating,
    evaluator_rating: Rating | None = None,
    user_override_rating: Rating | None = None,
    evaluation: Evaluation | None = None,
    question_id: int | None = None,
    question_attempt_id: int | None = None,
    response_ms: int | None = None,
    is_retest: bool = False,
    now: datetime | None = None,
) -> ReviewLog:
    """Advance FSRS and append to `review_logs`.

    `review_logs` is APPEND ONLY (§6): this function only ever inserts.
    """
    now = now or _now()
    scheduler = load_scheduler(session)

    before = to_card(item)
    due_before = _aware(item.due_at)
    stability_before = item.fsrs_stability
    difficulty_before = item.fsrs_difficulty

    after, _ = scheduler.review_card(
        before, final_rating, now,
        review_duration=response_ms if response_ms else None,
    )
    apply_card(item, after)
    item.reps += 1
    if final_rating is Rating.Again:
        item.lapses += 1
    session.add(item)

    row = ReviewLog(
        review_item_id=item.id,
        concept_id=item.concept_id,
        dimension=item.dimension,
        question_id=question_id,
        question_attempt_id=question_attempt_id,
        rating=int(final_rating),
        evaluator_rating=int(evaluator_rating) if evaluator_rating else None,
        user_override_rating=(
            int(user_override_rating) if user_override_rating else None
        ),
        evaluator_json=(
            json.dumps({
                "key_point_hits": evaluation.key_point_hits,
                "factually_incorrect_claims": evaluation.factually_incorrect_claims,
                "misconceptions": evaluation.misconceptions,
                "feedback": evaluation.feedback,
                "suggested_rating": evaluation.suggested_rating,
            }) if evaluation else None
        ),
        response_ms=response_ms,
        due_before=due_before,
        due_after=item.due_at,
        stability_before=stability_before,
        stability_after=item.fsrs_stability,
        difficulty_before=difficulty_before,
        difficulty_after=item.fsrs_difficulty,
        is_retest=is_retest,
        created_at=now,
    )
    session.add(row)
    session.flush()
    return row


def apply_retest(session: Session, item: ReviewItem, retest_rating: Rating,
                 now: datetime | None = None) -> bool:
    """Spec §9.5 **[LOCKED]** — the retest scheduling rule.

    "The *first* attempt is authoritative for FSRS. A retest may shorten the
    relearning step (if the item is in relearning and the retest passes,
    advance the relearning step) but **can never upgrade the original rating or
    push the due date further out**."

    Returns True when the relearning step was advanced.
    """
    now = now or _now()
    if item.fsrs_state is None:
        return False
    if State(int(item.fsrs_state)) is not State.Relearning:
        return False
    if retest_rating is Rating.Again:
        return False

    due_before = _aware(item.due_at)
    scheduler = load_scheduler(session)
    advanced, _ = scheduler.review_card(to_card(item), retest_rating, now)

    # Never push the due date further out than the original attempt set.
    if due_before is not None and advanced.due > due_before:
        return False

    apply_card(item, advanced)
    session.add(item)
    session.flush()
    return True


# --------------------------------------------------------------------------
# §10.4 Queue priority
# --------------------------------------------------------------------------

def priority(session: Session, item: ReviewItem, concept: Concept | None = None,
             now: datetime | None = None, weights: dict | None = None,
             interview_on: bool | None = None) -> float:
    """The §10.4 formula, verbatim."""
    now = now or _now()
    weights = weights or load_weights(session)
    if interview_on is None:
        interview_on = interview_mode_on(session)
    if concept is None:
        concept = session.get(Concept, item.concept_id)

    r = retrievability(session, item, now)
    forgetting_risk = 1 - r

    due_at = _aware(item.due_at)
    overdue_days = max(0, (now - due_at).days) if due_at else 0
    overdue_factor = 1 + math.log1p(overdue_days) * weights["w_overdue"]

    weakness = 1 + (item.lapses * weights["w_lapse"])
    importance = (concept.importance or 3.0) / 3.0
    coverage_gap = weights["w_gap"] if item.reps == 0 else 0.0
    interview_boost = (
        weights["w_interview"]
        if item.dimension == "interview" and interview_on
        else 0.0
    )

    return (forgetting_risk * overdue_factor * weakness * importance
            + coverage_gap + interview_boost)


def due_items(session: Session, now: datetime | None = None,
              subject_ids: tuple[int, ...] = (),
              include_new: bool = True) -> list[ReviewItem]:
    """Everything eligible to be served, suspended items excluded."""
    now = now or _now()
    stmt = select(ReviewItem).where(ReviewItem.suspended == False)  # noqa: E712
    items = list(session.exec(stmt).all())

    if subject_ids:
        allowed = {
            c.id for c in session.exec(
                select(Concept).where(Concept.subject_id.in_(subject_ids))
            ).all()
        }
        items = [i for i in items if i.concept_id in allowed]

    # A concept that has been archived (merged away) or deleted stops being
    # scheduled; a *stale* one keeps being scheduled (§7.4).
    live = {
        c.id for c in session.exec(
            select(Concept).where(Concept.deleted_at.is_(None))
        ).all()
    }
    items = [i for i in items if i.concept_id in live]

    out = []
    for item in items:
        if item.due_at is None:
            if include_new:
                out.append(item)
            continue
        if _aware(item.due_at) <= now:
            out.append(item)
    return out


def build_queue(session: Session, count: int, now: datetime | None = None,
                subject_ids: tuple[int, ...] = (),
                concept_ids: tuple[int, ...] = ()) -> list[ReviewItem]:
    """Spec §9.2 — due and overdue first by §10.4 priority, then new.

    `concept_ids` narrows the queue to one place in the tree: "on the Revision
    panel also I should have topic-wise / subtopic revision ready." The
    ordering within it is unchanged — priority still decides what comes first,
    it just has a smaller pool to choose from.
    """
    now = now or _now()
    weights = load_weights(session)
    interview_on = interview_mode_on(session)
    concepts = {
        c.id: c for c in session.exec(select(Concept)).all()
    }

    items = due_items(session, now, subject_ids)
    if concept_ids:
        wanted = set(concept_ids)
        items = [item for item in items if item.concept_id in wanted]
    scored = [
        (priority(session, item, concepts.get(item.concept_id), now,
                  weights, interview_on), item)
        for item in items
    ]
    # Highest priority first; never-reviewed items break ties last so that
    # genuinely due work leads.
    scored.sort(key=lambda pair: (-pair[0], pair[1].reps == 0, pair[1].id))
    return [item for _, item in scored[:count]]


# --------------------------------------------------------------------------
# §10.5 Mastery and badge decay
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Mastery:
    quality: float
    confidence: float
    freshness: float
    mastery: float
    badge: str
    reps: int
    last_reviewed_at: datetime | None


def _last_hit_ratios(session: Session, item: ReviewItem,
                     limit: int = 5) -> list[float]:
    """Rolling window of the last 5 attempts' key-point hit ratios."""
    logs = session.exec(
        select(ReviewLog)
        .where(ReviewLog.review_item_id == item.id)
        .order_by(ReviewLog.created_at.desc())
        .limit(limit)
    ).all()

    ratios: list[float] = []
    for row in logs:
        if not row.evaluator_json:
            continue
        try:
            payload = json.loads(row.evaluator_json)
        except json.JSONDecodeError:
            continue
        points = payload.get("key_point_hits") or []
        if not points:
            continue
        ratios.append(sum(1 for p in points if p.get("hit")) / len(points))
    return ratios


def mastery_of(session: Session, item: ReviewItem,
               now: datetime | None = None) -> Mastery:
    """Spec §10.5 **[LOCKED]**.

    Because `freshness` is FSRS retrievability, mastery decays with time on its
    own — a concept untouched for a month drifts from Mastered to Fading with
    no separate decay system.
    """
    now = now or _now()
    ratios = _last_hit_ratios(session, item)
    quality = sum(ratios) / len(ratios) if ratios else 0.0
    confidence = min(1.0, item.reps / 3.0)
    freshness = retrievability(session, item, now)
    value = quality * confidence * (0.4 + 0.6 * freshness)

    if item.reps == 0:
        badge = "untested"
    elif quality >= 0.85 and freshness >= 0.80 and item.reps >= 3:
        badge = "mastered"
    elif quality >= 0.85:
        badge = "fading"
    else:
        badge = "learning"

    return Mastery(
        quality=round(quality, 4),
        confidence=round(confidence, 4),
        freshness=round(freshness, 4),
        mastery=round(value, 4),
        badge=badge,
        reps=item.reps,
        last_reviewed_at=_aware(item.last_reviewed_at),
    )


#: Spec §10.5 — "apply and debug weighted 1.5x — those distinguish 'I remember
#: it' from 'I can use it'."
DIMENSION_WEIGHTS = {"apply": 1.5, "debug": 1.5}


def concept_mastery(session: Session, concept_id: int,
                    now: datetime | None = None) -> dict:
    items = session.exec(
        select(ReviewItem).where(ReviewItem.concept_id == concept_id)
    ).all()
    active = [i for i in items if not i.suspended]
    if not active:
        return {"concept_id": concept_id, "mastery": None, "badge": "untested",
                "dimensions": {}}

    per_dimension = {i.dimension: mastery_of(session, i, now) for i in active}
    weighted = sum(
        m.mastery * DIMENSION_WEIGHTS.get(dim, 1.0)
        for dim, m in per_dimension.items()
    )
    total_weight = sum(DIMENSION_WEIGHTS.get(dim, 1.0) for dim in per_dimension)
    value = weighted / total_weight if total_weight else 0.0

    badges = [m.badge for m in per_dimension.values()]
    if all(b == "untested" for b in badges):
        badge = "untested"
    elif all(b == "mastered" for b in badges):
        badge = "mastered"
    elif any(b == "fading" for b in badges):
        badge = "fading"
    else:
        badge = "learning"

    return {
        "concept_id": concept_id,
        "mastery": round(value, 4),
        "badge": badge,
        "dimensions": {
            dim: {
                "mastery": m.mastery, "badge": m.badge, "quality": m.quality,
                "freshness": m.freshness, "reps": m.reps,
                "last_reviewed_at": (
                    m.last_reviewed_at.isoformat() if m.last_reviewed_at else None
                ),
            }
            for dim, m in per_dimension.items()
        },
    }


def set_interview_mode(session: Session, enabled: bool) -> int:
    """Spec §10.1 — one toggle unsuspends every interview item, or suspends
    them again. Returns how many items changed."""
    row = session.get(Setting, INTERVIEW_MODE_KEY)
    if row is None:
        session.add(Setting(key=INTERVIEW_MODE_KEY,
                            value_json=json.dumps(enabled), updated_at=_now()))
    else:
        row.value_json = json.dumps(enabled)
        row.updated_at = _now()
        session.add(row)

    items = session.exec(
        select(ReviewItem).where(ReviewItem.dimension == "interview")
    ).all()
    changed = 0
    for item in items:
        if item.suspended == (not enabled):
            continue
        item.suspended = not enabled
        item.updated_at = _now()
        session.add(item)
        changed += 1
    session.flush()
    return changed
