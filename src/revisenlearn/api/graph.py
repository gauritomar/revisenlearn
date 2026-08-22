"""Graph console endpoints (spec §15, §13)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .. import graph as service
from ..db import get_session
from ..identity import normalise, store_concept_embedding
from ..models import EDGE_RELATION_TYPES, Concept, ConceptAlias, ConceptEdge
from ..pipeline.stages import creates_cycle

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EdgeCreate(BaseModel):
    source_concept_id: int
    target_concept_id: int
    relation_type: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ConceptEdit(BaseModel):
    """Spec §13.3 — the node editor."""

    canonical_name: str | None = Field(default=None, min_length=1, max_length=300)
    definition: str | None = None
    importance: float | None = Field(default=None, ge=1, le=5)
    difficulty: float | None = Field(default=None, ge=1, le=5)
    subject_id: int | None = None
    topic_id: int | None = None
    subtopic_id: int | None = None
    coverage_profile: dict | None = None


@router.get("/graph")
def graph(
    subject_id: int | None = Query(default=None),
    topic_id: int | None = Query(default=None),
    mastery: str | None = Query(default=None),
    relation_type: str | None = Query(default=None),
    job_id: int | None = Query(default=None),
    view: str = Query(default="entire_graph"),
    concept_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> dict:
    if view not in service.SAVED_VIEWS:
        raise HTTPException(400, f"view must be one of {service.SAVED_VIEWS}")
    return service.build_graph(
        session, subject_id=subject_id, topic_id=topic_id, mastery=mastery,
        relation_type=relation_type, job_id=job_id, view=view,
        concept_id=concept_id, search=search,
    )


@router.get("/graph/queues")
def queues(session: Session = Depends(get_session)) -> dict:
    return service.queue_counts(session)


@router.get("/graph/edges")
def list_edges(job_id: int | None = Query(default=None),
               status: str = Query(default="proposed"),
               session: Session = Depends(get_session)) -> list[dict]:
    if status == "proposed":
        return service.proposed_edges(session, job_id)
    rows = session.exec(
        select(ConceptEdge).where(ConceptEdge.status == status,
                                  ConceptEdge.deleted_at.is_(None))
    ).all()
    return [
        {"id": e.id, "source_id": e.source_concept_id,
         "target_id": e.target_concept_id, "relation_type": e.relation_type,
         "status": e.status, "confidence": e.confidence}
        for e in rows
    ]


@router.post("/graph/edges", status_code=201)
def create_edge(payload: EdgeCreate,
                session: Session = Depends(get_session)) -> dict:
    """A user-created edge is accepted immediately — they are the authority."""
    if payload.relation_type not in EDGE_RELATION_TYPES:
        raise HTTPException(400, f"relation_type must be one of {EDGE_RELATION_TYPES}")
    if payload.source_concept_id == payload.target_concept_id:
        raise HTTPException(400, "A concept cannot relate to itself")
    for concept_id in (payload.source_concept_id, payload.target_concept_id):
        if session.get(Concept, concept_id) is None:
            raise HTTPException(404, f"Concept {concept_id} not found")

    conflict = (
        payload.relation_type == "prerequisite_of"
        and creates_cycle(session, payload.source_concept_id,
                          payload.target_concept_id)
    )
    edge = ConceptEdge(
        source_concept_id=payload.source_concept_id,
        target_concept_id=payload.target_concept_id,
        relation_type=payload.relation_type,
        confidence=payload.confidence,
        created_by="user",
        # §8.4 — a cycle is never silently dropped; it is flagged for the user.
        status="proposed" if conflict else "accepted",
    )
    session.add(edge)
    session.flush()
    return {"id": edge.id, "status": edge.status, "cycle_conflict": conflict}


@router.post("/graph/edges/{edge_id}/accept")
def accept_edge(edge_id: int, session: Session = Depends(get_session)) -> dict:
    edge = session.get(ConceptEdge, edge_id)
    if edge is None or edge.deleted_at is not None:
        raise HTTPException(404, "Edge not found")

    if edge.relation_type == "prerequisite_of" and creates_cycle(
        session, edge.source_concept_id, edge.target_concept_id
    ):
        # Spec §8.4 — accepting this would close a loop in the DAG.
        raise HTTPException(
            409,
            "Accepting this would create a prerequisite cycle. "
            "Flip its direction or reject it.",
        )

    edge.status = "accepted"
    session.add(edge)
    session.flush()
    return {"id": edge.id, "status": edge.status}


@router.post("/graph/edges/{edge_id}/reject")
def reject_edge(edge_id: int, session: Session = Depends(get_session)) -> dict:
    edge = session.get(ConceptEdge, edge_id)
    if edge is None or edge.deleted_at is not None:
        raise HTTPException(404, "Edge not found")
    edge.status = "rejected"
    session.add(edge)
    session.flush()
    return {"id": edge.id, "status": edge.status}


@router.post("/graph/edges/{edge_id}/flip")
def flip_edge(edge_id: int, session: Session = Depends(get_session)) -> dict:
    """Spec §13.2 — "accept / reject / flip direction"."""
    edge = session.get(ConceptEdge, edge_id)
    if edge is None or edge.deleted_at is not None:
        raise HTTPException(404, "Edge not found")
    edge.source_concept_id, edge.target_concept_id = (
        edge.target_concept_id, edge.source_concept_id
    )
    session.add(edge)
    session.flush()
    conflict = (
        edge.relation_type == "prerequisite_of"
        and creates_cycle(session, edge.source_concept_id,
                          edge.target_concept_id)
    )
    return {"id": edge.id, "source_id": edge.source_concept_id,
            "target_id": edge.target_concept_id, "cycle_conflict": conflict}


@router.delete("/graph/edges/{edge_id}", status_code=204)
def delete_edge(edge_id: int, session: Session = Depends(get_session)) -> None:
    edge = session.get(ConceptEdge, edge_id)
    if edge is None or edge.deleted_at is not None:
        raise HTTPException(404, "Edge not found")
    edge.deleted_at = _now()
    session.add(edge)


@router.get("/graph/auto-merged")
def auto_merged(session: Session = Depends(get_session)) -> list[dict]:
    return service.auto_merged(session)


@router.get("/graph/orphans")
def orphans(session: Session = Depends(get_session)) -> list[dict]:
    return service.orphans(session)


@router.get("/graph/missing-prerequisites")
def missing_prerequisites(session: Session = Depends(get_session)) -> list[dict]:
    return service.missing_prerequisites(session)


@router.get("/graph/concepts/{concept_id}")
def concept_detail(concept_id: int,
                   session: Session = Depends(get_session)) -> dict:
    try:
        return service.concept_detail(session, concept_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None


@router.patch("/graph/concepts/{concept_id}")
def edit_concept(concept_id: int, payload: ConceptEdit,
                 session: Session = Depends(get_session)) -> dict:
    """Spec §13.3 — "rename (old name auto-becomes an alias)"."""
    import json as _json

    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, "Concept not found")

    fields = payload.model_dump(exclude_unset=True)
    profile = fields.pop("coverage_profile", None)

    if "canonical_name" in fields and fields["canonical_name"] != concept.canonical_name:
        old = concept.canonical_name
        existing = session.exec(
            select(ConceptAlias).where(ConceptAlias.concept_id == concept_id,
                                       ConceptAlias.alias == old)
        ).first()
        if existing is None:
            session.add(ConceptAlias(concept_id=concept_id, alias=old,
                                     normalised_alias=normalise(old),
                                     source="manual"))
        concept.canonical_name = fields["canonical_name"]
        concept.normalised_name = normalise(fields["canonical_name"])
        fields.pop("canonical_name")

    for field, value in fields.items():
        setattr(concept, field, value)
    if profile is not None:
        concept.coverage_profile_json = _json.dumps(profile)
        # A newly enabled dimension needs a review item (§10.2).
        from ..pipeline.coverage import ensure_review_items

        session.flush()
        ensure_review_items(session, concept)

    concept.updated_at = _now()
    session.add(concept)
    session.flush()

    if "definition" in fields or payload.canonical_name is not None:
        store_concept_embedding(session, concept)

    return service.concept_detail(session, concept_id)
