"""The knowledge graph and its work queues (spec §13 **[LOCKED]**).

"This is a curation workspace, not a decoration."

Node styling data (mastery badge, importance) and edge styling data
(relation_type, proposed/accepted) are computed here so the client draws rather
than decides.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from .models import (
    Concept,
    ConceptAlias,
    ConceptEdge,
    ConceptMerge,
    ConceptSource,
    LLMRun,
    NoteBlock,
    ReviewItem,
    ReviewLog,
    Subject,
    Subtopic,
    Topic,
)
from .scheduling import concept_mastery

log = logging.getLogger(__name__)

#: Spec §13.2 tab 4 — "a log of `decided_by='auto'` merges from the last 30
#: days, each with an Undo button. This is how the user builds trust in the
#: thresholds."
AUTO_MERGE_WINDOW_DAYS = 30

#: Spec §13.1 saved views.
SAVED_VIEWS = (
    "entire_graph", "subject", "topic", "neighbourhood",
    "weak_concepts", "orphans", "missing_prerequisites", "stale_concepts",
)

WEAK_BADGES = ("learning", "untested")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------

def _live_concepts(session: Session) -> list[Concept]:
    return list(session.exec(
        select(Concept).where(Concept.deleted_at.is_(None))
    ).all())


def _live_edges(session: Session) -> list[ConceptEdge]:
    return list(session.exec(
        select(ConceptEdge).where(
            ConceptEdge.deleted_at.is_(None),
            ConceptEdge.status != "rejected",
        )
    ).all())


def neighbours_within(session: Session, concept_id: int, hops: int = 2) -> set[int]:
    """Spec §13.1 saved view — "Concept neighbourhood (2 hops)"."""
    adjacency: dict[int, set[int]] = {}
    for edge in _live_edges(session):
        adjacency.setdefault(edge.source_concept_id, set()).add(edge.target_concept_id)
        adjacency.setdefault(edge.target_concept_id, set()).add(edge.source_concept_id)

    seen = {concept_id}
    frontier = {concept_id}
    for _ in range(max(0, hops)):
        nxt: set[int] = set()
        for node in frontier:
            nxt |= adjacency.get(node, set()) - seen
        seen |= nxt
        frontier = nxt
        if not frontier:
            break
    return seen


def orphan_ids(session: Session) -> set[int]:
    """Spec §13.2 tab 5 — concepts with no edges at all."""
    connected: set[int] = set()
    for edge in _live_edges(session):
        connected.add(edge.source_concept_id)
        connected.add(edge.target_concept_id)
    return {c.id for c in _live_concepts(session)} - connected


def missing_prerequisite_ids(session: Session) -> set[int]:
    """Concepts nothing is a prerequisite of and which require nothing —
    isolated in the prerequisite DAG specifically, so the ordering of study is
    unknown for them."""
    with_prereq: set[int] = set()
    for edge in _live_edges(session):
        if edge.relation_type == "prerequisite_of":
            with_prereq.add(edge.source_concept_id)
            with_prereq.add(edge.target_concept_id)
    # Only concepts that are hard enough to plausibly need one.
    return {
        c.id for c in _live_concepts(session)
        if c.id not in with_prereq and (c.difficulty or 0) >= 3
    }


def build_graph(
    session: Session,
    *,
    subject_id: int | None = None,
    topic_id: int | None = None,
    mastery: str | None = None,
    relation_type: str | None = None,
    job_id: int | None = None,
    view: str = "entire_graph",
    concept_id: int | None = None,
    search: str | None = None,
) -> dict:
    """Nodes and edges, with everything the client needs to style them.

    Spec §13.1: "Nodes coloured by mastery badge state, sized by importance.
    Edges styled by `relation_type`, dashed when `status='proposed'`."
    """
    concepts = _live_concepts(session)
    edges = _live_edges(session)

    subjects = {s.id: s for s in session.exec(select(Subject)).all()}
    topics = {t.id: t for t in session.exec(select(Topic)).all()}
    subtopics = {s.id: s for s in session.exec(select(Subtopic)).all()}

    keep = {c.id for c in concepts}

    if subject_id is not None:
        keep &= {c.id for c in concepts if c.subject_id == subject_id}
    if topic_id is not None:
        keep &= {c.id for c in concepts if c.topic_id == topic_id}
    if search:
        needle = search.strip().lower()
        keep &= {
            c.id for c in concepts
            if needle in c.canonical_name.lower()
            or needle in (c.definition or "").lower()
        }

    # Spec §13.4 — "Selecting one dims everything the job did not touch". The
    # server marks what the job touched; the client dims rather than removes,
    # so the surrounding structure stays visible.
    touched_by_job: set[int] = set()
    if job_id is not None:
        touched_by_job = {c.id for c in concepts if c.created_by_job_id == job_id}
        touched_by_job |= {
            s.concept_id for s in session.exec(
                select(ConceptSource).where(ConceptSource.job_id == job_id)
            ).all()
        }

    if view == "neighbourhood" and concept_id is not None:
        keep &= neighbours_within(session, concept_id, hops=2)
    elif view == "orphans":
        keep &= orphan_ids(session)
    elif view == "missing_prerequisites":
        keep &= missing_prerequisite_ids(session)
    elif view == "stale_concepts":
        keep &= {c.id for c in concepts if c.status == "stale"}

    mastery_by_id = {c.id: concept_mastery(session, c.id) for c in concepts
                     if c.id in keep}

    if view == "weak_concepts":
        keep &= {
            cid for cid, m in mastery_by_id.items()
            if m["badge"] in WEAK_BADGES
        }
    if mastery:
        keep &= {cid for cid, m in mastery_by_id.items()
                 if m["badge"] == mastery}

    nodes = []
    for concept in concepts:
        if concept.id not in keep:
            continue
        info = mastery_by_id.get(concept.id) or {"badge": "untested",
                                                 "mastery": None}
        nodes.append({
            "id": concept.id,
            "name": concept.canonical_name,
            "status": concept.status,
            "badge": info["badge"],
            "mastery": info["mastery"],
            "importance": concept.importance or 3.0,
            "difficulty": concept.difficulty,
            "subject": subjects[concept.subject_id].name if concept.subject_id in subjects else None,
            "topic": topics[concept.topic_id].name if concept.topic_id in topics else None,
            "subtopic": subtopics[concept.subtopic_id].name if concept.subtopic_id in subtopics else None,
            "dimmed": bool(job_id is not None and concept.id not in touched_by_job),
        })

    edge_rows = []
    for edge in edges:
        if edge.source_concept_id not in keep or edge.target_concept_id not in keep:
            continue
        if relation_type and edge.relation_type != relation_type:
            continue
        edge_rows.append({
            "id": edge.id,
            "source": edge.source_concept_id,
            "target": edge.target_concept_id,
            "relation_type": edge.relation_type,
            "status": edge.status,
            "confidence": edge.confidence,
            "created_by": edge.created_by,
            "job_id": edge.job_id,
            "dimmed": bool(job_id is not None and edge.job_id != job_id),
        })

    return {
        "view": view,
        "nodes": nodes,
        "edges": edge_rows,
        "counts": {"nodes": len(nodes), "edges": len(edge_rows)},
    }


# --------------------------------------------------------------------------
# §13.2 Work queue
# --------------------------------------------------------------------------

def queue_counts(session: Session) -> dict:
    """The count badge on each tab."""
    merge_queue = session.exec(
        select(ConceptMerge).where(ConceptMerge.decided_by.is_(None),
                                   ConceptMerge.reverted_at.is_(None))
    ).all()
    proposed = session.exec(
        select(ConceptEdge).where(ConceptEdge.status == "proposed",
                                  ConceptEdge.deleted_at.is_(None))
    ).all()
    stale = session.exec(
        select(Concept).where(Concept.status == "stale",
                              Concept.deleted_at.is_(None))
    ).all()
    cutoff = _now() - timedelta(days=AUTO_MERGE_WINDOW_DAYS)
    auto = [
        m for m in session.exec(
            select(ConceptMerge).where(ConceptMerge.decided_by == "auto",
                                       ConceptMerge.reverted_at.is_(None))
        ).all()
        if (m.created_at if m.created_at.tzinfo
            else m.created_at.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    return {
        "merge_queue": len(merge_queue),
        "proposed_edges": len(proposed),
        "stale_concepts": len(stale),
        "auto_merged": len(auto),
        "orphans": len(orphan_ids(session)),
    }


def proposed_edges(session: Session, job_id: int | None = None) -> list[dict]:
    """Spec §13.2 tab 2 — "accept / reject / flip direction. Cycle conflicts
    highlighted with the offending path drawn on the graph.\""""
    from .pipeline.stages import creates_cycle

    stmt = select(ConceptEdge).where(ConceptEdge.status == "proposed",
                                     ConceptEdge.deleted_at.is_(None))
    if job_id is not None:
        stmt = stmt.where(ConceptEdge.job_id == job_id)
    rows = session.exec(stmt.order_by(ConceptEdge.confidence.desc())).all()

    out = []
    for edge in rows:
        source = session.get(Concept, edge.source_concept_id)
        target = session.get(Concept, edge.target_concept_id)
        conflict = (
            edge.relation_type == "prerequisite_of"
            and creates_cycle(session, edge.source_concept_id,
                              edge.target_concept_id)
        )
        out.append({
            "id": edge.id,
            "source_id": edge.source_concept_id,
            "target_id": edge.target_concept_id,
            "source_name": source.canonical_name if source else "(missing)",
            "target_name": target.canonical_name if target else "(missing)",
            "relation_type": edge.relation_type,
            "confidence": edge.confidence,
            "created_by": edge.created_by,
            "job_id": edge.job_id,
            "cycle_conflict": conflict,
            "cycle_path": (
                cycle_path(session, edge.source_concept_id,
                           edge.target_concept_id) if conflict else []
            ),
        })
    return out


def cycle_path(session: Session, source_id: int, target_id: int) -> list[int]:
    """The offending path, so §13.2 can draw it on the graph."""
    accepted = session.exec(
        select(ConceptEdge).where(
            ConceptEdge.relation_type == "prerequisite_of",
            ConceptEdge.status == "accepted",
            ConceptEdge.deleted_at.is_(None),
        )
    ).all()
    adjacency: dict[int, list[int]] = {}
    for edge in accepted:
        adjacency.setdefault(edge.source_concept_id, []).append(
            edge.target_concept_id
        )

    stack = [(target_id, [target_id])]
    seen: set[int] = set()
    while stack:
        node, path = stack.pop()
        if node == source_id:
            return path
        if node in seen:
            continue
        seen.add(node)
        for nxt in adjacency.get(node, []):
            stack.append((nxt, path + [nxt]))
    return []


def auto_merged(session: Session) -> list[dict]:
    """Spec §13.2 tab 4 — the last 30 days of auto-merges, each undoable."""
    cutoff = _now() - timedelta(days=AUTO_MERGE_WINDOW_DAYS)
    rows = session.exec(
        select(ConceptMerge)
        .where(ConceptMerge.decided_by == "auto")
        .order_by(ConceptMerge.created_at.desc())
    ).all()

    out = []
    for row in rows:
        created = (row.created_at if row.created_at.tzinfo
                   else row.created_at.replace(tzinfo=timezone.utc))
        if created < cutoff:
            continue
        a = session.get(Concept, row.merged_from_id)
        b = session.get(Concept, row.merged_into_id)
        out.append({
            "id": row.id,
            "merged_from_id": row.merged_from_id,
            "merged_into_id": row.merged_into_id,
            "merged_from_name": a.canonical_name if a else "(missing)",
            "merged_into_name": b.canonical_name if b else "(missing)",
            "similarity": row.similarity,
            "created_at": created.isoformat(),
            "reverted_at": row.reverted_at.isoformat() if row.reverted_at else None,
            "job_id": row.job_id,
        })
    return out


def orphans(session: Session) -> list[dict]:
    ids = orphan_ids(session)
    return [
        {"id": c.id, "name": c.canonical_name, "status": c.status,
         "importance": c.importance}
        for c in _live_concepts(session) if c.id in ids
    ]


def missing_prerequisites(session: Session) -> list[dict]:
    ids = missing_prerequisite_ids(session)
    return [
        {"id": c.id, "name": c.canonical_name, "difficulty": c.difficulty}
        for c in _live_concepts(session) if c.id in ids
    ]


# --------------------------------------------------------------------------
# §13.3 Direct editing — the node inspector
# --------------------------------------------------------------------------

def concept_detail(session: Session, concept_id: int) -> dict:
    """Everything §13.3 says selecting a node should open: aliases, coverage,
    source notes, review history and token cost."""
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise LookupError("Concept not found")

    aliases = session.exec(
        select(ConceptAlias).where(ConceptAlias.concept_id == concept_id)
    ).all()

    sources = []
    for source in session.exec(
        select(ConceptSource).where(ConceptSource.concept_id == concept_id)
    ).all():
        block = session.get(NoteBlock, source.note_block_id)
        sources.append({
            "note_id": source.note_id,
            "note_block_id": source.note_block_id,
            "text": block.text if block else None,
            "invalidated": source.invalidated_at is not None,
            "job_id": source.job_id,
        })

    history = []
    for row in session.exec(
        select(ReviewLog)
        .where(ReviewLog.concept_id == concept_id)
        .order_by(ReviewLog.created_at.desc())
        .limit(30)
    ).all():
        history.append({
            "dimension": row.dimension,
            "rating": row.rating,
            "evaluator_rating": row.evaluator_rating,
            "user_override_rating": row.user_override_rating,
            "is_retest": row.is_retest,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })

    runs = session.exec(
        select(LLMRun).where(LLMRun.concept_id == concept_id)
    ).all()

    items = session.exec(
        select(ReviewItem).where(ReviewItem.concept_id == concept_id)
    ).all()

    edges = []
    for edge in _live_edges(session):
        if concept_id not in (edge.source_concept_id, edge.target_concept_id):
            continue
        other_id = (edge.target_concept_id if edge.source_concept_id == concept_id
                    else edge.source_concept_id)
        other = session.get(Concept, other_id)
        edges.append({
            "id": edge.id,
            "direction": "out" if edge.source_concept_id == concept_id else "in",
            "other_id": other_id,
            "other_name": other.canonical_name if other else "(missing)",
            "relation_type": edge.relation_type,
            "status": edge.status,
        })

    profile = {}
    if concept.coverage_profile_json:
        try:
            profile = json.loads(concept.coverage_profile_json)
        except json.JSONDecodeError:
            profile = {}

    return {
        "id": concept.id,
        "canonical_name": concept.canonical_name,
        "definition": concept.definition,
        "status": concept.status,
        "importance": concept.importance,
        "difficulty": concept.difficulty,
        "subject_id": concept.subject_id,
        "topic_id": concept.topic_id,
        "subtopic_id": concept.subtopic_id,
        "coverage_profile": profile,
        "aliases": [{"id": a.id, "alias": a.alias, "source": a.source}
                    for a in aliases],
        "sources": sources,
        "edges": edges,
        "review_items": [
            {"dimension": i.dimension, "reps": i.reps, "lapses": i.lapses,
             "suspended": i.suspended,
             "due_at": i.due_at.isoformat() if i.due_at else None}
            for i in items
        ],
        "history": history,
        "mastery": concept_mastery(session, concept_id),
        "cost": {
            "generations": len(runs),
            "input_tokens": sum(r.input_tokens for r in runs),
            "output_tokens": sum(r.output_tokens for r in runs),
            "estimated_cost_usd": round(
                sum(r.estimated_cost_usd or 0.0 for r in runs), 6
            ),
        },
    }
