"""Request/response models. Pydantic v2 via SQLModel."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


# --- Hierarchy -------------------------------------------------------------

class SubjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    colour: Optional[str] = None
    sort_order: int = 0


class SubjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    colour: Optional[str] = None
    sort_order: Optional[int] = None


class TopicCreate(BaseModel):
    subject_id: int
    name: str = Field(min_length=1, max_length=200)
    sort_order: int = 0


class TopicUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    sort_order: Optional[int] = None


class SubtopicCreate(BaseModel):
    topic_id: int
    name: str = Field(min_length=1, max_length=200)
    sort_order: int = 0


class SubtopicUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    sort_order: Optional[int] = None


class SubtopicOut(BaseModel):
    id: int
    topic_id: int
    name: str
    sort_order: int


class TopicOut(BaseModel):
    id: int
    subject_id: int
    name: str
    sort_order: int
    subtopics: list[SubtopicOut] = []


class SubjectOut(BaseModel):
    id: int
    name: str
    colour: Optional[str] = None
    sort_order: int
    topics: list[TopicOut] = []


# --- Notes -----------------------------------------------------------------

class BlockIn(BaseModel):
    """One block in a full-note save. ``id`` is present for existing blocks."""

    id: Optional[int] = None
    position: int
    block_type: str = "paragraph"
    text: str = ""


class BlockOut(BaseModel):
    id: int
    note_id: int
    position: int
    block_type: str
    text: str
    content_hash: str
    processed_hash: Optional[str] = None
    #: Derived for the §4.2 indicator so the frontend does not re-implement it.
    state: str  # unprocessed | processed | stale


class NoteCreate(BaseModel):
    title: Optional[str] = None
    study_date: Optional[date] = None
    subject_id: Optional[int] = None
    topic_id: Optional[int] = None
    subtopic_id: Optional[int] = None
    resource_id: Optional[int] = None


class NoteUpdate(BaseModel):
    title: Optional[str] = None


class NoteOut(BaseModel):
    id: int
    title: str
    study_date: date
    subject_id: Optional[int] = None
    topic_id: Optional[int] = None
    subtopic_id: Optional[int] = None
    resource_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    blocks: list[BlockOut] = []
    #: The §4.2 header counter: "12 processed · 4 new · 2 edited".
    counts: dict[str, int] = {}


class BlocksSave(BaseModel):
    """Autosave payload — the full block list for the note (spec §4.1)."""

    blocks: list[BlockIn]


# --- Search ----------------------------------------------------------------

class SearchHit(BaseModel):
    kind: str  # note_block | concept
    note_id: Optional[int] = None
    note_title: Optional[str] = None
    note_block_id: Optional[int] = None
    concept_id: Optional[int] = None
    title: str
    snippet: str
    study_date: Optional[date] = None


class SearchResults(BaseModel):
    query: str
    hits: list[SearchHit]
