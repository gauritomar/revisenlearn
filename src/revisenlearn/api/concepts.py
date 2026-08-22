"""Concepts and the merge queue (spec §15, §7).

Phase 4 exposes the identity subsystem: concepts can be created by hand,
matched, merged and un-merged, and the merge queue can be worked through. The
pipeline that creates them automatically arrives in Phase 5.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..identity import (
    load_thresholds,
    merge_concepts,
    most_similar,
    normalise,
    resolve_concept,
    revert_merge,
    store_concept_embedding,
)
from ..db import get_session
from ..models import Concept, ConceptAlias, ConceptMerge, ConceptSource

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

class ConceptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    definition: str | None = None
    subject_id: int | None = None
    topic_id: int | None = None
    subtopic_id: int | None = None
    importance: float | None = Field(default=None, ge=1, le=5)
    difficulty: float | None = Field(default=None, ge=1, le=5)
    coverage_profile: dict | None = None
    #: When false, skip §7.2 matching and always create a new concept. The
    #: graph console uses this to add something it knows is distinct.
    resolve: bool = True


class ConceptUpdate(BaseModel):
    canonical_name: str | None = Field(default=None, min_length=1, max_length=300)
    definition: str | None = None
    importance: float | None = Field(default=None, ge=1, le=5)
    difficulty: float | None = Field(default=None, ge=1, le=5)
    status: str | None = None
    coverage_profile: dict | None = None


class ConceptOut(BaseModel):
    id: int
    canonical_name: str
    normalised_name: str
    definition: str | None = None
    subject_id: int | None = None
    topic_id: int | None = None
    subtopic_id: int | None = None
    importance: float | None = None
    difficulty: float | None = None
    status: str
    coverage_profile: dict | None = None
    aliases: list[str] = []
    source_count: int = 0
    created_at: datetime


class ResolveResult(BaseModel):
    action: str            # exact | auto_merge | queued | new
    similarity: float | None = None
    concept: ConceptOut


class MergeRequest(BaseModel):
    merged_from_id: int
    merged_into_id: int


class MergeOut(BaseModel):
    id: int
    merged_from_id: int
    merged_into_id: int
    merged_from_name: str | None = None
    merged_into_name: str | None = None
    similarity: float | None = None
    decided_by: str | None = None
    created_at: datetime
    reverted_at: datetime | None = None


class AliasCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=300)


class SimilarOut(BaseModel):
    concept: ConceptOut | None = None
    similarity: float
    thresholds: dict


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------

def _out(session: Session, concept: Concept) -> ConceptOut:
    aliases = session.exec(
        select(ConceptAlias)
        .where(ConceptAlias.concept_id == concept.id)
        .order_by(ConceptAlias.id)
    ).all()
    source_count = len(
        session.exec(
            select(ConceptSource).where(
                ConceptSource.concept_id == concept.id,
                ConceptSource.invalidated_at.is_(None),
            )
        ).all()
    )
    profile = None
    if concept.coverage_profile_json:
        try:
            profile = json.loads(concept.coverage_profile_json)
        except json.JSONDecodeError:
            profile = None

    return ConceptOut(
        id=concept.id,
        canonical_name=concept.canonical_name,
        normalised_name=concept.normalised_name,
        definition=concept.definition,
        subject_id=concept.subject_id,
        topic_id=concept.topic_id,
        subtopic_id=concept.subtopic_id,
        importance=concept.importance,
        difficulty=concept.difficulty,
        status=concept.status,
        coverage_profile=profile,
        aliases=[a.alias for a in aliases],
        source_count=source_count,
        created_at=concept.created_at,
    )


def _get_concept(session: Session, concept_id: int) -> Concept:
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, "Concept not found")
    return concept


# --------------------------------------------------------------------------
# Concepts
# --------------------------------------------------------------------------

@router.get("/concepts", response_model=list[ConceptOut])
def list_concepts(
    subject_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> list[ConceptOut]:
    stmt = select(Concept)
    if not include_archived:
        stmt = stmt.where(Concept.deleted_at.is_(None))
    if subject_id is not None:
        stmt = stmt.where(Concept.subject_id == subject_id)
    if status is not None:
        stmt = stmt.where(Concept.status == status)
    if q:
        stmt = stmt.where(Concept.normalised_name.contains(normalise(q)))
    rows = session.exec(stmt.order_by(Concept.canonical_name)).all()
    return [_out(session, c) for c in rows]


@router.post("/concepts", response_model=ResolveResult, status_code=201)
def create_concept(payload: ConceptCreate,
                   session: Session = Depends(get_session)) -> ResolveResult:
    """Create a concept, running it through §7.2 identity resolution.

    The response says which branch was taken, so the caller can tell "this was
    a duplicate and merged" from "this is new".
    """
    if not payload.resolve:
        from ..identity import _create_concept  # deliberate: bypass matching

        concept = _create_concept(
            session,
            name=payload.name,
            normalised=normalise(payload.name),
            definition=payload.definition,
            subject_id=payload.subject_id,
            topic_id=payload.topic_id,
            subtopic_id=payload.subtopic_id,
            importance=payload.importance,
            difficulty=payload.difficulty,
            coverage_profile=payload.coverage_profile,
            job_id=None,
        )
        return ResolveResult(action="new", similarity=None,
                             concept=_out(session, concept))

    result = resolve_concept(
        session,
        name=payload.name,
        definition=payload.definition,
        subject_id=payload.subject_id,
        topic_id=payload.topic_id,
        subtopic_id=payload.subtopic_id,
        importance=payload.importance,
        difficulty=payload.difficulty,
        coverage_profile=payload.coverage_profile,
    )
    return ResolveResult(
        action=result.action,
        similarity=result.similarity,
        concept=_out(session, result.concept),
    )


@router.get("/concepts/similar", response_model=SimilarOut)
def similar(
    name: str = Query(min_length=1),
    definition: str | None = Query(default=None),
    subject_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
) -> SimilarOut:
    """What would §7.2 match this against, and how strongly? Used by the graph
    console before committing to a merge."""
    match, score = most_similar(session, name, definition, subject_id)
    thresholds = load_thresholds(session)
    return SimilarOut(
        concept=_out(session, match) if match else None,
        similarity=score,
        thresholds={"auto_merge": thresholds.auto_merge,
                    "merge_queue": thresholds.merge_queue},
    )


@router.get("/concepts/{concept_id}", response_model=ConceptOut)
def get_concept(concept_id: int,
                session: Session = Depends(get_session)) -> ConceptOut:
    return _out(session, _get_concept(session, concept_id))


@router.patch("/concepts/{concept_id}", response_model=ConceptOut)
def update_concept(concept_id: int, payload: ConceptUpdate,
                   session: Session = Depends(get_session)) -> ConceptOut:
    concept = _get_concept(session, concept_id)
    fields = payload.model_dump(exclude_unset=True)

    if "status" in fields and fields["status"] not in ("active", "stale", "archived"):
        raise HTTPException(400, "status must be active, stale or archived")

    profile = fields.pop("coverage_profile", None)
    for field, value in fields.items():
        setattr(concept, field, value)
    if profile is not None:
        concept.coverage_profile_json = json.dumps(profile)

    if "canonical_name" in fields:
        concept.normalised_name = normalise(concept.canonical_name)

    concept.updated_at = _now()
    session.add(concept)
    session.flush()

    # The embedding is of "{name}. {definition}", so either changing it
    # invalidates the stored vector.
    if "canonical_name" in fields or "definition" in fields:
        store_concept_embedding(session, concept)

    return _out(session, concept)


@router.post("/concepts/{concept_id}/aliases", response_model=ConceptOut)
def add_alias(concept_id: int, payload: AliasCreate,
              session: Session = Depends(get_session)) -> ConceptOut:
    concept = _get_concept(session, concept_id)
    from ..identity import _add_alias_if_new

    _add_alias_if_new(session, concept, payload.alias, source="manual")
    return _out(session, concept)


@router.delete("/concepts/{concept_id}", status_code=204)
def delete_concept(concept_id: int,
                   session: Session = Depends(get_session)) -> None:
    """Spec §7.4 — the user deleting a stale concept soft-deletes it, hard-
    deletes its MCQs, and suspends its review items. Nothing leaves the
    database except the MCQs, which the spec explicitly permits."""
    from ..models import MCQ, ReviewItem

    concept = _get_concept(session, concept_id)
    now = _now()

    concept.deleted_at = now
    concept.status = "archived"
    concept.updated_at = now
    session.add(concept)

    for mcq in session.exec(select(MCQ).where(MCQ.concept_id == concept_id)).all():
        session.delete(mcq)

    for item in session.exec(
        select(ReviewItem).where(ReviewItem.concept_id == concept_id)
    ).all():
        item.suspended = True
        item.updated_at = now
        session.add(item)


# --------------------------------------------------------------------------
# The merge queue (spec §13.2, §15 /api/graph/*)
# --------------------------------------------------------------------------

def _merge_out(session: Session, row: ConceptMerge) -> MergeOut:
    a = session.get(Concept, row.merged_from_id)
    b = session.get(Concept, row.merged_into_id)
    return MergeOut(
        id=row.id,
        merged_from_id=row.merged_from_id,
        merged_into_id=row.merged_into_id,
        merged_from_name=a.canonical_name if a else None,
        merged_into_name=b.canonical_name if b else None,
        similarity=row.similarity,
        decided_by=row.decided_by,
        created_at=row.created_at,
        reverted_at=row.reverted_at,
    )


@router.get("/graph/merge-queue", response_model=list[MergeOut])
def merge_queue(session: Session = Depends(get_session)) -> list[MergeOut]:
    """Spec §7.2 — the 0.82–0.92 band, awaiting a human. `decided_by IS NULL`
    is what makes a row a queue entry."""
    rows = session.exec(
        select(ConceptMerge)
        .where(ConceptMerge.decided_by.is_(None),
               ConceptMerge.reverted_at.is_(None))
        .order_by(ConceptMerge.similarity.desc())
    ).all()
    return [_merge_out(session, r) for r in rows]


@router.get("/graph/merges", response_model=list[MergeOut])
def merge_history(session: Session = Depends(get_session)) -> list[MergeOut]:
    """Every merge, decided or not. The auto-merge log §21.1 wants for tuning
    the thresholds from evidence."""
    rows = session.exec(
        select(ConceptMerge).order_by(ConceptMerge.created_at.desc())
    ).all()
    return [_merge_out(session, r) for r in rows]


@router.post("/graph/merge", response_model=MergeOut)
def do_merge(payload: MergeRequest,
             session: Session = Depends(get_session)) -> MergeOut:
    a = _get_concept(session, payload.merged_from_id)
    b = _get_concept(session, payload.merged_into_id)
    if a.id == b.id:
        raise HTTPException(400, "A concept cannot be merged into itself")
    if a.status == "archived":
        raise HTTPException(409, "That concept has already been merged away")

    # A queued proposal for this pair is now decided.
    queued = session.exec(
        select(ConceptMerge).where(
            ConceptMerge.merged_from_id == a.id,
            ConceptMerge.merged_into_id == b.id,
            ConceptMerge.decided_by.is_(None),
            ConceptMerge.reverted_at.is_(None),
        )
    ).first()

    row = merge_concepts(session, merged_from=a, merged_into=b,
                         similarity=queued.similarity if queued else None,
                         decided_by="user")
    if queued is not None:
        session.delete(queued)
        session.flush()
    return _merge_out(session, row)


@router.post("/graph/merge/{merge_id}/reject", response_model=dict)
def reject_merge(merge_id: int,
                 session: Session = Depends(get_session)) -> dict:
    """Dismiss a queued suggestion. The two concepts stay separate."""
    row = session.get(ConceptMerge, merge_id)
    if row is None:
        raise HTTPException(404, "Merge not found")
    if row.decided_by is not None:
        raise HTTPException(409, "That merge has already been applied")
    session.delete(row)
    return {"rejected": merge_id}


@router.post("/graph/merge/{merge_id}/revert", response_model=ConceptOut)
def do_revert(merge_id: int,
              session: Session = Depends(get_session)) -> ConceptOut:
    """Spec §7.3 — merges are reversible via `concept_merges.reverted_at`."""
    row = session.get(ConceptMerge, merge_id)
    if row is None:
        raise HTTPException(404, "Merge not found")
    if row.decided_by is None:
        raise HTTPException(409, "That merge was never applied")
    try:
        restored = revert_merge(session, row)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return _out(session, restored)


@router.get("/graph/stale", response_model=list[ConceptOut])
def stale_concepts(session: Session = Depends(get_session)) -> list[ConceptOut]:
    """Spec §7.4 — concepts whose source blocks are all gone. They keep being
    scheduled; losing the source text is not losing the knowledge."""
    rows = session.exec(
        select(Concept)
        .where(Concept.status == "stale", Concept.deleted_at.is_(None))
        .order_by(Concept.updated_at.desc())
    ).all()
    return [_out(session, c) for c in rows]
