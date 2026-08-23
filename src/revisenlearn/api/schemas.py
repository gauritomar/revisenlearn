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
    #: The article, lecture or problem set this page came from.
    url: Optional[str] = None


class SubjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    colour: Optional[str] = None
    sort_order: Optional[int] = None
    url: Optional[str] = None


class TopicCreate(BaseModel):
    subject_id: int
    name: str = Field(min_length=1, max_length=200)
    sort_order: int = 0
    url: Optional[str] = None


class TopicUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    sort_order: Optional[int] = None
    url: Optional[str] = None


class SubtopicCreate(BaseModel):
    topic_id: int
    name: str = Field(min_length=1, max_length=200)
    sort_order: int = 0
    url: Optional[str] = None


class SubtopicUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    sort_order: Optional[int] = None
    url: Optional[str] = None


class LessonBrief(BaseModel):
    """A lesson as the sidebar needs it (consolidated addendum §5).

    The counts are what decide whether the row gets a chevron at all —
    "Lessons also have a chevron if they have checklist items worth
    previewing" — so they travel with the tree rather than costing a
    request per lesson.
    """

    id: int
    topic_id: int
    subtopic_id: Optional[int] = None
    name: str
    status: str
    position: int
    url: Optional[str] = None
    checklist_total: int = 0
    checklist_done: int = 0


class SubtopicOut(BaseModel):
    id: int
    topic_id: int
    name: str
    sort_order: int
    url: Optional[str] = None
    lessons: list[LessonBrief] = []


class TopicOut(BaseModel):
    id: int
    subject_id: int
    name: str
    sort_order: int
    url: Optional[str] = None
    subtopics: list[SubtopicOut] = []
    #: Lessons hanging straight off the topic, with no subtopic.
    lessons: list[LessonBrief] = []


class SubjectOut(BaseModel):
    id: int
    name: str
    colour: Optional[str] = None
    sort_order: int
    url: Optional[str] = None
    topics: list[TopicOut] = []


# --- Notes -----------------------------------------------------------------

class BlockIn(BaseModel):
    """One block in a full-note save. ``id`` is present for existing blocks."""

    id: Optional[int] = None
    position: int
    block_type: str = "paragraph"
    text: str = ""
    #: checklist_item blocks (consolidated addendum §2).
    checked: bool = False
    url: Optional[str] = None
    #: `code_block` blocks only: the grammar to highlight with.
    language: Optional[str] = None
    #: One level of nesting only.
    parent_block_id: Optional[int] = None
    #: For a child whose parent is also new and so has no id yet: the parent's
    #: index in this same payload. Ignored when ``parent_block_id`` is given.
    parent_index: Optional[int] = None


class BlockOut(BaseModel):
    id: int
    note_id: int
    position: int
    block_type: str
    text: str
    checked: bool = False
    url: Optional[str] = None
    language: Optional[str] = None
    parent_block_id: Optional[int] = None
    #: Held back from the pipeline until the user says otherwise.
    skip_processing: bool = False
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
    #: When set, `POST /api/notes/ensure` returns the note for this resource
    #: and day rather than the subtopic's own note (spec §5.1 split view).
    resource_id: Optional[int] = None
    #: Consolidated addendum §3 — the primary path. A Lesson has ONE
    #: continuous note; `study_date` is ignored when this is set.
    lesson_id: Optional[int] = None


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
    lesson_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    blocks: list[BlockOut] = []
    #: The §4.2 header counter: "12 processed · 4 new · 2 edited".
    counts: dict[str, int] = {}


class BlocksSave(BaseModel):
    """Autosave payload — the full block list for the note (spec §4.1)."""

    blocks: list[BlockIn]


# --- Resources -------------------------------------------------------------

class TitleProbe(BaseModel):
    url: str


class TitleProbeResult(BaseModel):
    """``title`` is None when the fetch failed for any reason — the client then
    falls back to the raw URL (spec §5.1)."""

    title: Optional[str] = None
    resource_type: str = "other"


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    colour: Optional[str] = None


class ResourceCreate(BaseModel):
    #: One of these is required; everything else has a sensible default so the
    #: add flow stays under five seconds (spec §5.1).
    url: Optional[str] = None
    title: Optional[str] = None
    resource_type: Optional[str] = None
    description: Optional[str] = None
    status: str = "inbox"
    priority: int = 0
    subject_id: Optional[int] = None
    topic_id: Optional[int] = None
    subtopic_id: Optional[int] = None
    progress_pct: int = Field(default=0, ge=0, le=100)
    progress_note: Optional[str] = None


class ResourceUpdate(BaseModel):
    url: Optional[str] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    resource_type: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = None
    subject_id: Optional[int] = None
    topic_id: Optional[int] = None
    subtopic_id: Optional[int] = None
    #: Spec §5 — set by hand with a slider. Never computed.
    progress_pct: Optional[int] = Field(default=None, ge=0, le=100)
    progress_note: Optional[str] = None



class TagOut(BaseModel):
    id: int
    name: str
    colour: Optional[str] = None


class ResourceOut(BaseModel):
    id: int
    title: str
    url: Optional[str] = None
    resource_type: str
    description: Optional[str] = None
    status: str
    priority: int
    subject_id: Optional[int] = None
    topic_id: Optional[int] = None
    subtopic_id: Optional[int] = None
    progress_pct: int
    progress_note: Optional[str] = None
    #: What it is about. Tags survived the library rework; headings did not.
    tags: list[TagOut] = []
    created_at: datetime
    last_opened_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# --- Calendar --------------------------------------------------------------

class CalendarPill(BaseModel):
    """A topic written about on a given day (spec §14: "topic pills per day")."""

    topic_id: int
    name: str
    colour: Optional[str] = None


class CalendarDay(BaseModel):
    date: date
    note_count: int
    topics: list[CalendarPill] = []
    #: Concepts falling due on this day. Overdue work is counted on today,
    #: which is when the user actually has to do it.
    due_count: int = 0


class CalendarMonth(BaseModel):
    month: str  # YYYY-MM
    #: Only days with something on them — writing, or work coming back. The
    #: grid is drawn client-side.
    days: list[CalendarDay] = []


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
