"""Coverage profiles and review items (spec §10.1, §10.2 **[LOCKED]**).

"A `review_item` is created for each `true` dimension. No `review_item` means
no scheduling and no cost."
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from ..models import DIMENSIONS, Concept, ReviewItem

log = logging.getLogger(__name__)

#: Spec §10.1 — interview items are "created but suspended". A single Settings
#: toggle unsuspends them all; default off.
SUSPENDED_BY_DEFAULT = ("interview",)

#: A concept with no profile still needs somewhere to start.
FALLBACK_PROFILE = {
    "recall": True, "explain": True, "apply": False,
    "debug": False, "synthesis": False, "interview": False,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def read_profile(concept: Concept) -> dict:
    if not concept.coverage_profile_json:
        return dict(FALLBACK_PROFILE)
    try:
        profile = json.loads(concept.coverage_profile_json)
    except json.JSONDecodeError:
        return dict(FALLBACK_PROFILE)
    if not isinstance(profile, dict):
        return dict(FALLBACK_PROFILE)
    return {d: bool(profile.get(d, False)) for d in DIMENSIONS}


def ensure_review_items(session: Session, concept: Concept) -> list[ReviewItem]:
    """Create a review item per enabled dimension. Idempotent.

    Existing items are never removed here — §10.2 says "Removals are never
    automatic — only the user removes a dimension."
    """
    profile = read_profile(concept)

    existing = {
        item.dimension: item
        for item in session.exec(
            select(ReviewItem).where(ReviewItem.concept_id == concept.id)
        ).all()
    }

    created: list[ReviewItem] = []
    for dimension in DIMENSIONS:
        if not profile.get(dimension):
            continue
        if dimension in existing:
            continue
        item = ReviewItem(
            concept_id=concept.id,
            dimension=dimension,
            suspended=dimension in SUSPENDED_BY_DEFAULT,
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(item)
        created.append(item)

    session.flush()
    return created


def stage_planning_coverage(session: Session, job, ctx) -> None:
    """Write coverage profiles and create review items for this job's
    concepts."""
    total = 0
    for concept_id in sorted(ctx.concept_ids):
        concept = session.get(Concept, concept_id)
        if concept is None or concept.deleted_at is not None:
            continue  # merged away during resolving_identity
        if not concept.coverage_profile_json:
            concept.coverage_profile_json = json.dumps(FALLBACK_PROFILE)
            session.add(concept)
        total += len(ensure_review_items(session, concept))
    session.flush()
    if total:
        log.info("Created %s review item(s)", total)
