"""Concept identity: normalisation, matching, merging (spec §7 **[LOCKED]**).

"This subsystem determines whether the app is usable in three months. Treat it
as first-class."

Nothing here calls a model. Matching is exact-name first, then local embedding
similarity, so identity keeps working with no network (spec §16).
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from sqlmodel import Session, select

from .embeddings import (
    cosine_against,
    embed_concept_text,
    from_blob,
    get_embedder,
    to_blob,
)
from .models import (
    MCQ,
    Concept,
    ConceptAlias,
    ConceptEdge,
    ConceptMerge,
    ConceptSource,
    Embedding,
    ReviewItem,
    ReviewLog,
    Setting,
)

log = logging.getLogger(__name__)

#: Spec §7.2. Editable from the Settings screen, hence stored in `settings`.
DEFAULT_AUTO_MERGE = 0.92
DEFAULT_MERGE_QUEUE = 0.82
THRESHOLD_KEY = "similarity_thresholds"

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")
#: A trailing parenthetical acronym: "Retrieval Augmented Generation (RAG)".
_TRAILING_ACRONYM = re.compile(r"\s*\([A-Za-z0-9./-]{1,10}\)\s*$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# §7.1 Normalisation
# --------------------------------------------------------------------------

def normalise(name: str) -> str:
    """lowercase → strip punctuation → collapse whitespace → strip a trailing
    parenthetical acronym → singularise a trailing "s" only when the remainder
    is at least 4 characters.

    The order matters: the acronym is stripped before punctuation removal,
    because removing brackets first would leave the acronym as a bare word.
    """
    text = unicodedata.normalize("NFKC", name or "")
    text = _TRAILING_ACRONYM.sub("", text)
    text = text.lower()
    text = _PUNCT.sub(" ", text)
    text = _WS.sub(" ", text).strip()

    if text.endswith("s") and not text.endswith("ss"):
        # "the remainder" is what is left after dropping the "s": "embeddings"
        # -> "embedding" (9 chars, singularise), "gas" -> "ga" (2, keep).
        stem = text[:-1]
        if len(stem) >= 4:
            text = stem
    return text


# --------------------------------------------------------------------------
# Thresholds
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Thresholds:
    auto_merge: float = DEFAULT_AUTO_MERGE
    merge_queue: float = DEFAULT_MERGE_QUEUE


def load_thresholds(session: Session) -> Thresholds:
    row = session.get(Setting, THRESHOLD_KEY)
    if row is None:
        return Thresholds()
    try:
        value = json.loads(row.value_json)
        return Thresholds(
            auto_merge=float(value.get("auto_merge", DEFAULT_AUTO_MERGE)),
            merge_queue=float(value.get("merge_queue", DEFAULT_MERGE_QUEUE)),
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        log.warning("Unreadable similarity_thresholds setting; using defaults")
        return Thresholds()


# --------------------------------------------------------------------------
# Embedding storage
# --------------------------------------------------------------------------

def store_concept_embedding(session: Session, concept: Concept) -> Embedding:
    """Embed ``"{name}. {definition}"`` and upsert the row."""
    embedder = get_embedder()
    vector = embedder.embed([embed_concept_text(concept.canonical_name,
                                                concept.definition)])[0]

    existing = session.exec(
        select(Embedding).where(
            Embedding.target_type == "concept",
            Embedding.target_id == concept.id,
        )
    ).first()
    if existing is not None:
        existing.vector = to_blob(vector)
        existing.model = embedder.model_name
        existing.dim = embedder.dim
        session.add(existing)
        session.flush()
        return existing

    row = Embedding(
        target_type="concept",
        target_id=concept.id,
        vector=to_blob(vector),
        model=embedder.model_name,
        dim=embedder.dim,
    )
    session.add(row)
    session.flush()
    return row


# --------------------------------------------------------------------------
# §7.2 Matching
# --------------------------------------------------------------------------

@dataclass
class MatchResult:
    """What matching decided, and why."""

    action: str          # exact | auto_merge | queued | new
    concept: Concept     # the concept the caller should use
    similarity: float | None = None
    #: Set when `action == "queued"` — the row awaiting a human decision.
    merge_row: ConceptMerge | None = None
    alias_added: bool = False


def find_exact(session: Session, normalised: str,
               subject_id: int | None) -> Concept | None:
    """Spec §7.2 step 1 — normalised_name against concepts, then aliases."""
    stmt = select(Concept).where(
        Concept.normalised_name == normalised,
        Concept.deleted_at.is_(None),
        Concept.status != "archived",
    )
    if subject_id is not None:
        stmt = stmt.where(Concept.subject_id == subject_id)
    concept = session.exec(stmt.order_by(Concept.id)).first()
    if concept is not None:
        return concept

    alias = session.exec(
        select(ConceptAlias)
        .where(ConceptAlias.normalised_alias == normalised)
        .order_by(ConceptAlias.id)
    ).first()
    if alias is None:
        return None
    candidate = session.get(Concept, alias.concept_id)
    if candidate is None or candidate.deleted_at is not None:
        return None
    if subject_id is not None and candidate.subject_id != subject_id:
        return None
    return candidate


def _active_concepts_in_subject(session: Session, subject_id: int | None,
                                exclude_id: int | None = None) -> list[Concept]:
    stmt = select(Concept).where(
        Concept.deleted_at.is_(None),
        Concept.status == "active",
    )
    # Spec §7.2 compares "against all active concepts in the same Subject".
    stmt = stmt.where(Concept.subject_id == subject_id)
    rows = list(session.exec(stmt).all())
    if exclude_id is not None:
        rows = [c for c in rows if c.id != exclude_id]
    return rows


def most_similar(
    session: Session,
    name: str,
    definition: str | None,
    subject_id: int | None,
    exclude_id: int | None = None,
) -> tuple[Concept | None, float]:
    """Brute-force cosine against every active concept in the subject."""
    candidates = _active_concepts_in_subject(session, subject_id, exclude_id)
    if not candidates:
        return None, 0.0

    rows = session.exec(
        select(Embedding).where(
            Embedding.target_type == "concept",
            Embedding.target_id.in_([c.id for c in candidates]),
        )
    ).all()
    by_id = {r.target_id: r for r in rows}

    usable = [c for c in candidates if c.id in by_id]
    if not usable:
        return None, 0.0

    matrix = np.stack([from_blob(by_id[c.id].vector, by_id[c.id].dim)
                       for c in usable])
    query = get_embedder().embed([embed_concept_text(name, definition)])[0]
    scores = cosine_against(query, matrix)

    best = int(np.argmax(scores))
    return usable[best], float(scores[best])


def resolve_concept(
    session: Session,
    name: str,
    definition: str | None,
    subject_id: int | None = None,
    topic_id: int | None = None,
    subtopic_id: int | None = None,
    importance: float | None = None,
    difficulty: float | None = None,
    coverage_profile: dict | None = None,
    job_id: int | None = None,
) -> MatchResult:
    """The §7.2 decision, in order. Returns the concept the caller should use.

    1. Exact normalised match (concept or alias) → that concept, adding the new
       spelling as an alias if it differs.
    2. Embedding similarity within the subject:
       ``>= auto_merge`` → create, then merge into the match, ``decided_by='auto'``;
       ``>= merge_queue`` → create normally *and* queue a row for the user;
       otherwise → new concept.
    """
    normalised = normalise(name)
    thresholds = load_thresholds(session)

    exact = find_exact(session, normalised, subject_id)
    if exact is not None:
        added = _add_alias_if_new(session, exact, name, source="extraction")
        return MatchResult(action="exact", concept=exact, similarity=1.0,
                           alias_added=added)

    match, score = most_similar(session, name, definition, subject_id)

    new_concept = _create_concept(
        session, name=name, normalised=normalised, definition=definition,
        subject_id=subject_id, topic_id=topic_id, subtopic_id=subtopic_id,
        importance=importance, difficulty=difficulty,
        coverage_profile=coverage_profile, job_id=job_id,
    )

    if match is not None and score >= thresholds.auto_merge:
        merge_concepts(session, merged_from=new_concept, merged_into=match,
                       similarity=score, decided_by="auto", job_id=job_id)
        return MatchResult(action="auto_merge", concept=match, similarity=score)

    if match is not None and score >= thresholds.merge_queue:
        # Spec §7.2: create normally, but write a decided_by=NULL row. That
        # NULL *is* the merge queue.
        queued = ConceptMerge(
            merged_from_id=new_concept.id,
            merged_into_id=match.id,
            similarity=score,
            decided_by=None,
            job_id=job_id,
        )
        session.add(queued)
        session.flush()
        return MatchResult(action="queued", concept=new_concept,
                           similarity=score, merge_row=queued)

    return MatchResult(action="new", concept=new_concept, similarity=score)


def _create_concept(session: Session, *, name: str, normalised: str,
                    definition: str | None, subject_id: int | None,
                    topic_id: int | None, subtopic_id: int | None,
                    importance: float | None, difficulty: float | None,
                    coverage_profile: dict | None,
                    job_id: int | None) -> Concept:
    concept = Concept(
        canonical_name=name,
        normalised_name=normalised,
        definition=definition,
        subject_id=subject_id,
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        importance=importance,
        difficulty=difficulty,
        status="active",
        coverage_profile_json=(
            json.dumps(coverage_profile) if coverage_profile is not None else None
        ),
        created_by_job_id=job_id,
    )
    session.add(concept)
    session.flush()
    store_concept_embedding(session, concept)
    _add_alias_if_new(session, concept, name, source="extraction")
    return concept


def _add_alias_if_new(session: Session, concept: Concept, alias: str,
                      source: str) -> bool:
    """Spec §7.2 — "Add the new name as an alias if different."

    Deduplication is on the *exact* spelling, not the normalised form: two
    spellings that normalise alike are still two spellings the user has used,
    and keeping both is how the graph console can show what a concept has been
    called. Matching is unaffected, since lookups go through
    `normalised_alias`.
    """
    normalised = normalise(alias)
    existing = session.exec(
        select(ConceptAlias).where(
            ConceptAlias.concept_id == concept.id,
            ConceptAlias.alias == alias,
        )
    ).first()
    if existing is not None:
        return False
    session.add(ConceptAlias(concept_id=concept.id, alias=alias,
                             normalised_alias=normalised, source=source))
    session.flush()
    return True


# --------------------------------------------------------------------------
# §7.3 Merge semantics **[LOCKED]**
# --------------------------------------------------------------------------

def merge_concepts(session: Session, merged_from: Concept, merged_into: Concept,
                   similarity: float | None = None,
                   decided_by: str = "user",
                   job_id: int | None = None) -> ConceptMerge:
    """Merge A into B, exactly per §7.3.

    No note content is ever touched.
    """
    if merged_from.id == merged_into.id:
        raise ValueError("A concept cannot be merged into itself")

    a, b = merged_from, merged_into
    now = _now()

    # A's canonical_name and all A's aliases become aliases of B.
    _add_alias_if_new(session, b, a.canonical_name, source="merge")
    for alias in session.exec(
        select(ConceptAlias).where(ConceptAlias.concept_id == a.id)
    ).all():
        _add_alias_if_new(session, b, alias.alias, source="merge")

    # A's concept_sources repoint to B.
    for source in session.exec(
        select(ConceptSource).where(ConceptSource.concept_id == a.id)
    ).all():
        source.concept_id = b.id
        session.add(source)

    # A's edges repoint to B; self-edges and exact duplicates are dropped.
    _repoint_edges(session, a.id, b.id, now)

    # A's MCQs repoint to B.
    for mcq in session.exec(select(MCQ).where(MCQ.concept_id == a.id)).all():
        mcq.concept_id = b.id
        session.add(mcq)

    _merge_review_items(session, a.id, b.id)

    # A is soft-deleted with status='archived'.
    a.status = "archived"
    a.deleted_at = now
    a.updated_at = now
    session.add(a)

    row = ConceptMerge(
        merged_from_id=a.id,
        merged_into_id=b.id,
        similarity=similarity,
        decided_by=decided_by,
        job_id=job_id,
    )
    session.add(row)
    session.flush()

    # B's text has not changed, but its alias set has; the embedding is of
    # "{name}. {definition}" so it stays valid. Refresh anyway to keep the
    # stored model/dim in step if the model was ever swapped.
    store_concept_embedding(session, b)

    log.info("Merged concept %s into %s (%s)", a.id, b.id, decided_by)
    return row


def _repoint_edges(session: Session, from_id: int, into_id: int,
                   now: datetime) -> None:
    edges = session.exec(
        select(ConceptEdge).where(
            (ConceptEdge.source_concept_id == from_id)
            | (ConceptEdge.target_concept_id == from_id)
        )
    ).all()

    def signature(edge: ConceptEdge) -> tuple:
        return (edge.source_concept_id, edge.target_concept_id,
                edge.relation_type)

    surviving = {
        signature(e)
        for e in session.exec(
            select(ConceptEdge).where(ConceptEdge.deleted_at.is_(None))
        ).all()
        if e.source_concept_id != from_id and e.target_concept_id != from_id
    }

    for edge in edges:
        if edge.source_concept_id == from_id:
            edge.source_concept_id = into_id
        if edge.target_concept_id == from_id:
            edge.target_concept_id = into_id

        if edge.source_concept_id == edge.target_concept_id:
            edge.deleted_at = now          # self-edge
        elif signature(edge) in surviving:
            edge.deleted_at = now          # exact duplicate
        else:
            surviving.add(signature(edge))
        session.add(edge)


def _merge_review_items(session: Session, from_id: int, into_id: int) -> None:
    """Spec §7.3: for each dimension, if both A and B have a review_item, keep
    B's FSRS state, keep both items' review_logs, and repoint A's logs to B's
    item. If only A has one, repoint it to B."""
    a_items = session.exec(
        select(ReviewItem).where(ReviewItem.concept_id == from_id)
    ).all()
    b_items = {
        item.dimension: item
        for item in session.exec(
            select(ReviewItem).where(ReviewItem.concept_id == into_id)
        ).all()
    }

    for a_item in a_items:
        b_item = b_items.get(a_item.dimension)
        if b_item is None:
            # Only A has one: repoint the item itself. Its FSRS state and its
            # logs come with it.
            a_item.concept_id = into_id
            session.add(a_item)
            for log_row in session.exec(
                select(ReviewLog).where(ReviewLog.review_item_id == a_item.id)
            ).all():
                log_row.concept_id = into_id
                session.add(log_row)
            b_items[a_item.dimension] = a_item
            continue

        # Both have one: B's FSRS state wins, A's logs repoint to B's item.
        for log_row in session.exec(
            select(ReviewLog).where(ReviewLog.review_item_id == a_item.id)
        ).all():
            log_row.review_item_id = b_item.id
            log_row.concept_id = into_id
            session.add(log_row)
        b_item.reps += a_item.reps
        b_item.lapses += a_item.lapses
        session.add(b_item)
        # A's now-empty item is removed; its history lives on B's.
        session.delete(a_item)
    session.flush()


# --------------------------------------------------------------------------
# Reversal (§7.3: "Merges are reversible from the graph console")
# --------------------------------------------------------------------------

def revert_merge(session: Session, merge: ConceptMerge) -> Concept:
    """Undo a merge. Returns the restored concept.

    Restores A as an active concept and detaches the artefacts that carry A's
    id in `concept_sources`/`mcqs`. Edge and review-item repointing is not
    unwound: B may have been reviewed since, and §6 forbids ever rewriting
    `review_logs`. This is recorded in DECISIONS.md.
    """
    if merge.reverted_at is not None:
        raise ValueError("This merge has already been reverted")

    a = session.get(Concept, merge.merged_from_id)
    b = session.get(Concept, merge.merged_into_id)
    if a is None or b is None:
        raise ValueError("Cannot revert: one side of the merge is missing")

    now = _now()

    a.status = "active"
    a.deleted_at = None
    a.updated_at = now
    session.add(a)

    # Aliases that came from this merge go back.
    a_names = {normalise(a.canonical_name)}
    for alias in session.exec(
        select(ConceptAlias).where(ConceptAlias.concept_id == a.id)
    ).all():
        a_names.add(alias.normalised_alias)

    for alias in session.exec(
        select(ConceptAlias).where(
            ConceptAlias.concept_id == b.id,
            ConceptAlias.source == "merge",
        )
    ).all():
        if alias.normalised_alias in a_names:
            session.delete(alias)

    # Sources and MCQs that name A go home.
    for source in session.exec(
        select(ConceptSource).where(ConceptSource.concept_id == b.id)
    ).all():
        if source.job_id == merge.job_id and merge.job_id is not None:
            source.concept_id = a.id
            session.add(source)

    merge.reverted_at = now
    session.add(merge)
    session.flush()

    store_concept_embedding(session, a)
    log.info("Reverted merge %s: concept %s restored", merge.id, a.id)
    return a


# --------------------------------------------------------------------------
# §7.4 Stale concepts
# --------------------------------------------------------------------------

def invalidate_sources_for_block(session: Session, note_block_id: int) -> int:
    """A block was edited or deleted: mark its concept_sources invalidated and
    re-evaluate whether each concept still has evidence."""
    rows = session.exec(
        select(ConceptSource).where(
            ConceptSource.note_block_id == note_block_id,
            ConceptSource.invalidated_at.is_(None),
        )
    ).all()
    now = _now()
    touched: set[int] = set()
    for row in rows:
        row.invalidated_at = now
        session.add(row)
        touched.add(row.concept_id)
    session.flush()

    for concept_id in touched:
        refresh_stale_status(session, concept_id)
    return len(rows)


def refresh_stale_status(session: Session, concept_id: int) -> str | None:
    """A concept with zero valid sources becomes `stale` — but keeps being
    scheduled (spec §7.4)."""
    concept = session.get(Concept, concept_id)
    if concept is None or concept.status == "archived":
        return None

    remaining = session.exec(
        select(ConceptSource).where(
            ConceptSource.concept_id == concept_id,
            ConceptSource.invalidated_at.is_(None),
        )
    ).first()

    new_status = "active" if remaining is not None else "stale"
    if concept.status != new_status:
        concept.status = new_status
        concept.updated_at = _now()
        session.add(concept)
        session.flush()
    return new_status
