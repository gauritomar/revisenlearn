"""Structured-output schemas for the pipeline (spec §11.1).

"All calls use structured outputs with a Pydantic-derived JSON schema."
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import DIMENSIONS, EDGE_RELATION_TYPES


class CoverageProfile(BaseModel):
    """Spec §10.2 — which dimensions this concept needs."""

    recall: bool = True
    explain: bool = True
    apply: bool = False
    debug: bool = False
    synthesis: bool = False
    interview: bool = False

    def enabled(self) -> list[str]:
        return [d for d in DIMENSIONS if getattr(self, d, False)]


class ExtractedConcept(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    definition: str = Field(min_length=1)
    importance: int = Field(ge=1, le=5)
    difficulty: int = Field(ge=1, le=5)
    coverage_profile: CoverageProfile
    #: Spec §11.1 — "Attach the source block IDs for every concept."
    source_block_ids: list[int] = Field(default_factory=list)


class ExtractedEdge(BaseModel):
    source_name: str = Field(min_length=1)
    target_name: str = Field(min_length=1)
    relation_type: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)

    def is_valid_relation(self) -> bool:
        return self.relation_type in EDGE_RELATION_TYPES


class ExtractionResult(BaseModel):
    """The §11.1 output contract."""

    concepts: list[ExtractedConcept] = Field(default_factory=list)
    edges: list[ExtractedEdge] = Field(default_factory=list)
