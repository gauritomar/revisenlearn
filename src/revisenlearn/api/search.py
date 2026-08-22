"""Global search — the ⌘K palette (spec §15, §14.4).

Phase 1 is FTS5 only. The semantic half of "FTS5 + semantic" needs local
embeddings, which arrive in Phase 4; the response shape already carries both
kinds of hit so adding it is additive.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text as sql_text
from sqlmodel import Session

from ..db import get_session
from .schemas import SearchHit, SearchResults

router = APIRouter()

_TOKEN = re.compile(r"[\w']+", re.UNICODE)


def build_match_query(raw: str) -> str | None:
    """Turn free user text into a safe FTS5 MATCH expression.

    Every token is double-quoted, which neutralises FTS5 operators (``OR``,
    ``NEAR``, ``*``, ``-``) that would otherwise raise a syntax error on input
    the user never meant as an operator. The final token gets a ``*`` so the
    palette matches as you type.
    """
    tokens = _TOKEN.findall(raw or "")
    if not tokens:
        return None
    quoted = [f'"{t}"' for t in tokens[:-1]]
    quoted.append(f'"{tokens[-1]}"*')
    return " ".join(quoted)


@router.get("/search", response_model=SearchResults)
def search(
    q: str = Query(default="", description="Free text"),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> SearchResults:
    match = build_match_query(q)
    if match is None:
        return SearchResults(query=q, hits=[])

    hits: list[SearchHit] = []

    block_rows = session.exec(
        sql_text(
            """
            SELECT f.note_block_id  AS note_block_id,
                   f.note_id        AS note_id,
                   n.title          AS note_title,
                   n.study_date     AS study_date,
                   snippet(note_blocks_fts, 0, '<mark>', '</mark>', '…', 12) AS snippet
            FROM note_blocks_fts f
            JOIN notes n ON n.id = f.note_id
            WHERE note_blocks_fts MATCH :match
              AND n.deleted_at IS NULL
            ORDER BY bm25(note_blocks_fts)
            LIMIT :limit
            """
        ).bindparams(match=match, limit=limit)
    ).all()

    for row in block_rows:
        hits.append(
            SearchHit(
                kind="note_block",
                note_id=row.note_id,
                note_title=row.note_title,
                note_block_id=row.note_block_id,
                title=row.note_title or "Untitled note",
                snippet=row.snippet or "",
                study_date=row.study_date,
            )
        )

    concept_rows = session.exec(
        sql_text(
            """
            SELECT f.concept_id AS concept_id,
                   c.canonical_name AS canonical_name,
                   snippet(concepts_fts, 1, '<mark>', '</mark>', '…', 12) AS snippet
            FROM concepts_fts f
            JOIN concepts c ON c.id = f.concept_id
            WHERE concepts_fts MATCH :match
              AND c.deleted_at IS NULL
            ORDER BY bm25(concepts_fts)
            LIMIT :limit
            """
        ).bindparams(match=match, limit=limit)
    ).all()

    for row in concept_rows:
        hits.append(
            SearchHit(
                kind="concept",
                concept_id=row.concept_id,
                title=row.canonical_name,
                snippet=row.snippet or "",
            )
        )

    return SearchResults(query=q, hits=hits[:limit])
