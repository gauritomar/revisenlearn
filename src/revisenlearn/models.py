"""The full data model from spec §6 **[LOCKED]**.

Table and column names follow §6 exactly. Nothing is ever hard-deleted
(principle §1.7) — every table that the spec gives a ``deleted_at`` gets one,
and application code soft-deletes.

Only the hierarchy and note tables are exercised in Phase 1; the rest are
created by the initial migration so that later phases add data, not DDL.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Index, LargeBinary, Text, UniqueConstraint
from sqlmodel import Column, Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Enumerated values. Stored as plain strings (SQLite has no native enum);
# these constants exist so application code and tests agree on spelling.
# --------------------------------------------------------------------------

DIMENSIONS = ("recall", "explain", "apply", "debug", "synthesis", "interview")
RESOURCE_TYPES = (
    "youtube_video", "youtube_playlist", "article", "paper", "pdf",
    "book", "course", "problem_set", "other",
)
RESOURCE_STATUSES = ("inbox", "next", "in_progress", "completed", "archived")
CONCEPT_STATUSES = ("active", "stale", "archived")
EDGE_RELATION_TYPES = (
    "prerequisite_of", "related_to", "part_of",
    "contrasts_with", "depends_on", "causes",
)
EDGE_STATUSES = ("proposed", "accepted", "rejected")
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
SESSION_TYPES = ("practice", "revision")
LLM_TASKS = (
    "concept_extraction", "mcq_generation", "question_generation",
    "evaluation", "edge_proposal",
)
BLOCK_TYPES = (
    "paragraph", "heading1", "heading2", "heading3", "bullet_list_item",
    "numbered_list_item", "quote", "code_block", "divider",
    # Consolidated addendum §2. Typing "- [ ] text" makes one; "- [x] text"
    # makes it pre-checked. One level of nesting via `parent_block_id`.
    "checklist_item",
    # §3 — inserted automatically on the first edit of a new calendar day, so
    # a note spanning months stays navigable.
    "date_divider",
)


# --------------------------------------------------------------------------
# Hierarchy
# --------------------------------------------------------------------------

class Subject(SQLModel, table=True):
    __tablename__ = "subjects"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    colour: Optional[str] = None
    sort_order: int = 0
    #: The article, lecture or problem set this page came from, shown at the
    #: top of it so the source is one click away.
    url: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    deleted_at: Optional[datetime] = None


class Topic(SQLModel, table=True):
    __tablename__ = "topics"

    id: Optional[int] = Field(default=None, primary_key=True)
    subject_id: int = Field(foreign_key="subjects.id", index=True)
    name: str
    sort_order: int = 0
    #: The article, lecture or problem set this page came from, shown at the
    #: top of it so the source is one click away.
    url: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    deleted_at: Optional[datetime] = None


class Subtopic(SQLModel, table=True):
    __tablename__ = "subtopics"

    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topics.id", index=True)
    name: str
    sort_order: int = 0
    #: The article, lecture or problem set this page came from, shown at the
    #: top of it so the source is one click away.
    url: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    deleted_at: Optional[datetime] = None


class ResourceGroup(SQLModel, table=True):
    """A heading in the resource library.

    The user's shelf, named by them: "be able to group resources under
    different headings and within each it should be able to have certain
    tags". A resource belongs to at most one group — a heading is where a
    thing is filed, while tags are what it is about, and one of those has to
    be singular for the library to have a shape.
    """

    __tablename__ = "resource_groups"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    colour: Optional[str] = None
    position: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    deleted_at: Optional[datetime] = None


class Tag(SQLModel, table=True):
    __tablename__ = "tags"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    colour: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class Tagging(SQLModel, table=True):
    __tablename__ = "taggings"

    id: Optional[int] = Field(default=None, primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", index=True)
    target_type: str  # note | resource | concept
    target_id: int


# --------------------------------------------------------------------------
# Notes
# --------------------------------------------------------------------------

class Note(SQLModel, table=True):
    __tablename__ = "notes"
    __table_args__ = (Index("ix_notes_study_date", "study_date"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    study_date: date = Field(index=False)
    subject_id: Optional[int] = Field(default=None, foreign_key="subjects.id")
    topic_id: Optional[int] = Field(default=None, foreign_key="topics.id")
    subtopic_id: Optional[int] = Field(default=None, foreign_key="subtopics.id")
    resource_id: Optional[int] = Field(default=None, foreign_key="resources.id")
    #: Consolidated addendum §3 — a Lesson has ONE continuous note, not one per
    #: day. This is now the primary anchor, mirroring `resource_id`.
    #: `lesson_id IS NULL` remains a perfectly valid freeform note.
    lesson_id: Optional[int] = Field(default=None, foreign_key="lessons.id",
                                     index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    deleted_at: Optional[datetime] = None


class NoteBlock(SQLModel, table=True):
    __tablename__ = "note_blocks"
    __table_args__ = (Index("ix_note_blocks_note_position", "note_id", "position"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    note_id: int = Field(foreign_key="notes.id")
    position: int
    block_type: str = "paragraph"
    text: str = Field(sa_column=Column(Text, nullable=False, default=""))
    #: SHA-256 of the normalised text (spec §4.2).
    content_hash: str
    #: NULL = never processed; != content_hash = processed then edited (stale).
    processed_hash: Optional[str] = None

    # --- checklist_item blocks (consolidated addendum §2) -----------------
    #: The note block is the single source of truth for checked-ness. The
    #: `checklist_items` projection is derived from it and never diverges.
    checked: bool = False
    #: A URL written on this block. §4 auto-detects a Resource from it.
    url: Optional[str] = None
    #: `code_block` blocks only: which grammar to highlight with. Stored so a
    #: note reopens as it was written, rather than guessing from the text.
    language: Optional[str] = None
    #: One level of nesting only.
    parent_block_id: Optional[int] = Field(default=None,
                                           foreign_key="note_blocks.id")

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    deleted_at: Optional[datetime] = None


# --------------------------------------------------------------------------
# Resources
# --------------------------------------------------------------------------

class Resource(SQLModel, table=True):
    __tablename__ = "resources"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    url: Optional[str] = None
    resource_type: str = "other"
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    status: str = "inbox"
    priority: int = 0
    #: The heading this is filed under in the library, if any.
    group_id: Optional[int] = Field(default=None, foreign_key="resource_groups.id",
                                    index=True)
    subject_id: Optional[int] = Field(default=None, foreign_key="subjects.id")
    topic_id: Optional[int] = Field(default=None, foreign_key="topics.id")
    subtopic_id: Optional[int] = Field(default=None, foreign_key="subtopics.id")
    progress_pct: int = 0
    progress_note: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    last_opened_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


# --------------------------------------------------------------------------
# Concepts and identity
# --------------------------------------------------------------------------

class Concept(SQLModel, table=True):
    __tablename__ = "concepts"
    __table_args__ = (Index("ix_concepts_normalised_name", "normalised_name"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    canonical_name: str
    normalised_name: str
    definition: Optional[str] = Field(default=None, sa_column=Column(Text))
    subject_id: Optional[int] = Field(default=None, foreign_key="subjects.id")
    topic_id: Optional[int] = Field(default=None, foreign_key="topics.id")
    subtopic_id: Optional[int] = Field(default=None, foreign_key="subtopics.id")
    importance: Optional[float] = None
    difficulty: Optional[float] = None
    status: str = "active"
    coverage_profile_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_by_job_id: Optional[int] = Field(default=None, foreign_key="pipeline_jobs.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    deleted_at: Optional[datetime] = None


class ConceptAlias(SQLModel, table=True):
    __tablename__ = "concept_aliases"

    id: Optional[int] = Field(default=None, primary_key=True)
    concept_id: int = Field(foreign_key="concepts.id", index=True)
    alias: str
    normalised_alias: str = Field(index=True)
    source: str = "extraction"  # extraction | merge | manual
    created_at: datetime = Field(default_factory=utcnow)


class ConceptMerge(SQLModel, table=True):
    __tablename__ = "concept_merges"

    id: Optional[int] = Field(default=None, primary_key=True)
    merged_from_id: int = Field(foreign_key="concepts.id")
    merged_into_id: int = Field(foreign_key="concepts.id")
    similarity: Optional[float] = None
    #: NULL means "queued for the user to decide" (spec §7.2).
    decided_by: Optional[str] = None  # auto | user | NULL
    job_id: Optional[int] = Field(default=None, foreign_key="pipeline_jobs.id")
    created_at: datetime = Field(default_factory=utcnow)
    reverted_at: Optional[datetime] = None


class ConceptSource(SQLModel, table=True):
    __tablename__ = "concept_sources"
    __table_args__ = (Index("ix_concept_sources_concept_id", "concept_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    concept_id: int = Field(foreign_key="concepts.id")
    note_block_id: int = Field(foreign_key="note_blocks.id")
    note_id: int = Field(foreign_key="notes.id")
    job_id: Optional[int] = Field(default=None, foreign_key="pipeline_jobs.id")
    created_at: datetime = Field(default_factory=utcnow)
    invalidated_at: Optional[datetime] = None


class ConceptEdge(SQLModel, table=True):
    __tablename__ = "concept_edges"
    __table_args__ = (
        Index("ix_concept_edges_source", "source_concept_id"),
        Index("ix_concept_edges_target", "target_concept_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    source_concept_id: int = Field(foreign_key="concepts.id")
    target_concept_id: int = Field(foreign_key="concepts.id")
    relation_type: str
    confidence: Optional[float] = None
    created_by: str = "llm"  # llm | user
    status: str = "proposed"  # proposed | accepted | rejected
    job_id: Optional[int] = Field(default=None, foreign_key="pipeline_jobs.id")
    created_at: datetime = Field(default_factory=utcnow)
    deleted_at: Optional[datetime] = None


class Embedding(SQLModel, table=True):
    __tablename__ = "embeddings"
    __table_args__ = (Index("ix_embeddings_target", "target_type", "target_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    target_type: str  # concept | note_block
    target_id: int
    vector: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    model: str
    dim: int
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------
# MCQs
# --------------------------------------------------------------------------

class MCQ(SQLModel, table=True):
    __tablename__ = "mcqs"
    __table_args__ = (Index("ix_mcqs_concept_status", "concept_id", "status"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    concept_id: int = Field(foreign_key="concepts.id")
    dimension: str
    stem: str = Field(sa_column=Column(Text, nullable=False))
    options_json: str = Field(sa_column=Column(Text, nullable=False))
    correct_option_id: str
    explanation: Optional[str] = Field(default=None, sa_column=Column(Text))
    distractor_rationale_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    difficulty: Optional[float] = None
    status: str = "active"  # active | retired
    times_served: int = 0
    times_correct: int = 0
    consecutive_correct: int = 0
    last_served_at: Optional[datetime] = None
    prompt_version: Optional[str] = None
    model: Optional[str] = None
    job_id: Optional[int] = Field(default=None, foreign_key="pipeline_jobs.id")
    created_at: datetime = Field(default_factory=utcnow)
    retired_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


class MCQAttempt(SQLModel, table=True):
    __tablename__ = "mcq_attempts"

    id: Optional[int] = Field(default=None, primary_key=True)
    mcq_id: int = Field(foreign_key="mcqs.id", index=True)
    concept_id: int = Field(foreign_key="concepts.id")
    session_id: Optional[int] = Field(default=None, foreign_key="sessions.id")
    selected_option_id: Optional[str] = None
    is_correct: bool = False
    response_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------
# Prose questions
# --------------------------------------------------------------------------

class Question(SQLModel, table=True):
    __tablename__ = "questions"

    id: Optional[int] = Field(default=None, primary_key=True)
    concept_id: int = Field(foreign_key="concepts.id", index=True)
    review_item_id: Optional[int] = Field(default=None, foreign_key="review_items.id")
    dimension: str
    question_text: str = Field(sa_column=Column(Text, nullable=False))
    expected_answer: Optional[str] = Field(default=None, sa_column=Column(Text))
    key_points_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    common_misconceptions_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    difficulty: Optional[float] = None
    source_note_ids_json: Optional[str] = None
    generation_reason: Optional[str] = None
    prompt_version: Optional[str] = None
    model: Optional[str] = None
    embedding_id: Optional[int] = Field(default=None, foreign_key="embeddings.id")
    created_at: datetime = Field(default_factory=utcnow)
    deleted_at: Optional[datetime] = None


class QuestionAttempt(SQLModel, table=True):
    __tablename__ = "question_attempts"

    id: Optional[int] = Field(default=None, primary_key=True)
    question_id: int = Field(foreign_key="questions.id", index=True)
    review_item_id: Optional[int] = Field(default=None, foreign_key="review_items.id")
    session_id: Optional[int] = Field(default=None, foreign_key="sessions.id")
    user_answer: Optional[str] = Field(default=None, sa_column=Column(Text))
    is_retest: bool = False
    retest_of_attempt_id: Optional[int] = Field(
        default=None, foreign_key="question_attempts.id"
    )
    evaluator_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    evaluator_rating: Optional[int] = None
    user_override_rating: Optional[int] = None
    final_rating: Optional[int] = None
    response_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------
# Scheduling
# --------------------------------------------------------------------------

class ReviewItem(SQLModel, table=True):
    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint("concept_id", "dimension", name="uq_review_items_concept_dim"),
        Index("ix_review_items_due_at", "due_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    concept_id: int = Field(foreign_key="concepts.id")
    dimension: str
    fsrs_stability: Optional[float] = None
    fsrs_difficulty: Optional[float] = None
    fsrs_state: Optional[str] = None
    fsrs_step: Optional[int] = None
    due_at: Optional[datetime] = None
    last_reviewed_at: Optional[datetime] = None
    lapses: int = 0
    reps: int = 0
    suspended: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ReviewLog(SQLModel, table=True):
    """APPEND ONLY. No UPDATE, no DELETE, ever (spec §6)."""

    __tablename__ = "review_logs"
    __table_args__ = (Index("ix_review_logs_item_created", "review_item_id", "created_at"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    review_item_id: int = Field(foreign_key="review_items.id")
    concept_id: int = Field(foreign_key="concepts.id")
    dimension: str
    question_id: Optional[int] = Field(default=None, foreign_key="questions.id")
    question_attempt_id: Optional[int] = Field(
        default=None, foreign_key="question_attempts.id"
    )
    rating: Optional[int] = None
    evaluator_rating: Optional[int] = None
    user_override_rating: Optional[int] = None
    evaluator_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    response_ms: Optional[int] = None
    due_before: Optional[datetime] = None
    due_after: Optional[datetime] = None
    stability_before: Optional[float] = None
    stability_after: Optional[float] = None
    difficulty_before: Optional[float] = None
    difficulty_after: Optional[float] = None
    is_retest: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class Misconception(SQLModel, table=True):
    __tablename__ = "misconceptions"

    id: Optional[int] = Field(default=None, primary_key=True)
    concept_id: int = Field(foreign_key="concepts.id", index=True)
    text: str = Field(sa_column=Column(Text, nullable=False))
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)
    times_seen: int = 1
    resolved_at: Optional[datetime] = None


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------

class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_type: str  # practice | revision
    scope_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    planned_count: int = 0
    completed_count: int = 0
    correct_count: int = 0
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None


class SessionItem(SQLModel, table=True):
    __tablename__ = "session_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="sessions.id", index=True)
    position: int
    item_type: str  # mcq | question
    mcq_id: Optional[int] = Field(default=None, foreign_key="mcqs.id")
    question_id: Optional[int] = Field(default=None, foreign_key="questions.id")
    review_item_id: Optional[int] = Field(default=None, foreign_key="review_items.id")
    selection_bucket: Optional[str] = None  # new | failed | random | due
    served_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None


# --------------------------------------------------------------------------
# Pipeline and LLM accounting
# --------------------------------------------------------------------------

class PipelineJob(SQLModel, table=True):
    __tablename__ = "pipeline_jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    status: str = "queued"
    stage: Optional[str] = None
    subject_id: Optional[int] = Field(default=None, foreign_key="subjects.id")
    block_count: int = 0
    concepts_created: int = 0
    concepts_updated: int = 0
    concepts_merged: int = 0
    edges_proposed: int = 0
    mcqs_generated: int = 0
    error_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    #: Why it failed, when the provider told us something actionable:
    #: credits | auth | request | rate_limit. NULL means "no idea, retrying
    #: is as good a guess as any".
    error_reason: Optional[str] = None
    #: What the user can do about it, in a sentence.
    error_action: Optional[str] = Field(default=None, sa_column=Column(Text))
    retry_count: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class PipelineJobBlock(SQLModel, table=True):
    """The snapshot taken at button-press time (spec §4.3)."""

    __tablename__ = "pipeline_job_blocks"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="pipeline_jobs.id", index=True)
    note_block_id: int = Field(foreign_key="note_blocks.id")
    note_id: int = Field(foreign_key="notes.id")
    text_snapshot: str = Field(sa_column=Column(Text, nullable=False))
    hash_snapshot: str


class LLMRun(SQLModel, table=True):
    __tablename__ = "llm_runs"
    __table_args__ = (
        Index("ix_llm_runs_created_at", "created_at"),
        Index("ix_llm_runs_concept_id", "concept_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: Optional[int] = Field(default=None, foreign_key="pipeline_jobs.id")
    session_id: Optional[int] = Field(default=None, foreign_key="sessions.id")
    task: str
    provider: str = "gemini"
    model: str
    prompt_version: Optional[str] = None
    thinking_level: Optional[str] = None
    request_mode: str = "standard"  # standard | batch
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    latency_ms: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    success: bool = True
    error_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    concept_id: Optional[int] = Field(default=None, foreign_key="concepts.id")
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

class Setting(SQLModel, table=True):
    __tablename__ = "settings"

    key: str = Field(primary_key=True)
    value_json: str = Field(sa_column=Column(Text, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)

# --------------------------------------------------------------------------
# Lessons, Items and Todos (addendum §1, §3)
#
# A parallel tracking layer. Checking a box here never creates a concept and
# never touches FSRS (addendum §0.1) — concept extraction happens only when the
# user deliberately writes a note.
# --------------------------------------------------------------------------

#: `revisit` is "I need to come back to this" — not the same as never having
#: started, and the thing a red marker is for.
LESSON_STATUSES = ("not_started", "in_progress", "done", "revisit")


class Lesson(SQLModel, table=True):
    """A coherent chunk of study — the level progress is tracked at.

    Requires a Topic but not a Subtopic, mirroring how Notes already work.
    """

    __tablename__ = "lessons"
    __table_args__ = (Index("ix_lessons_topic_position", "topic_id", "position"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topics.id", index=True)
    subtopic_id: Optional[int] = Field(default=None, foreign_key="subtopics.id",
                                       index=True)
    name: str
    position: int = 0
    #: Directly settable by the user, not purely derived (addendum §4).
    #: not_started | in_progress | done | revisit — the last one is "I need to
    #: come back to this", which is a different thing from not having started.
    status: str = "not_started"
    #: The article, lecture or problem set this lesson came from.
    url: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    deleted_at: Optional[datetime] = None


class ChecklistItem(SQLModel, table=True):
    """A checklist line, **derived from a note block** (addendum §2).

    "checklist_items rows are created/updated/deleted automatically whenever a
    checklist_item block is saved … This table has no dedicated CRUD UI."

    So this is a projection, not an authored table: `note_block_id` is UNIQUE
    and every field mirrors the block. Toggling from Roadmap or the right panel
    writes through to `note_blocks`, and this row follows — never a second,
    divergent copy of the state.
    """

    __tablename__ = "checklist_items"
    __table_args__ = (
        UniqueConstraint("note_block_id", name="uq_checklist_note_block"),
        Index("ix_checklist_items_lesson", "lesson_id"),
        Index("ix_checklist_items_note", "note_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    note_block_id: int = Field(foreign_key="note_blocks.id")
    note_id: int = Field(foreign_key="notes.id")
    #: Null when the note is freeform rather than a lesson's note.
    lesson_id: Optional[int] = Field(default=None, foreign_key="lessons.id")
    parent_checklist_item_id: Optional[int] = Field(
        default=None, foreign_key="checklist_items.id"
    )
    text: str
    url: Optional[str] = None
    checked: bool = False
    completed_at: Optional[datetime] = None
    position: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Todo(SQLModel, table=True):
    """Standalone, not tied to a Lesson, Resource or Note (addendum §3).

    "Just a checkbox, a title, and an optional due date. No priority field, no
    status enum beyond done/not done."
    """

    __tablename__ = "todos"
    __table_args__ = (Index("ix_todos_due_date", "due_date"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    subject_id: Optional[int] = Field(default=None, foreign_key="subjects.id")
    topic_id: Optional[int] = Field(default=None, foreign_key="topics.id")
    due_date: Optional[date] = None
    done: bool = False
    completed_at: Optional[datetime] = None
    position: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    deleted_at: Optional[datetime] = None


# --------------------------------------------------------------------------
# Flexible linking (addendum §2)
#
# `notes.resource_id` stays as "the resource I was primarily working from",
# a convenience default. These cover everything beyond that one.
# --------------------------------------------------------------------------

class NoteLessonLink(SQLModel, table=True):
    __tablename__ = "note_lesson_links"
    __table_args__ = (
        UniqueConstraint("note_id", "lesson_id", name="uq_note_lesson"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    note_id: int = Field(foreign_key="notes.id", index=True)
    lesson_id: int = Field(foreign_key="lessons.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class NoteResourceLink(SQLModel, table=True):
    __tablename__ = "note_resource_links"
    __table_args__ = (
        UniqueConstraint("note_id", "resource_id", name="uq_note_resource"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    note_id: int = Field(foreign_key="notes.id", index=True)
    resource_id: int = Field(foreign_key="resources.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class LessonResourceLink(SQLModel, table=True):
    __tablename__ = "lesson_resource_links"
    __table_args__ = (
        UniqueConstraint("lesson_id", "resource_id", name="uq_lesson_resource"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    lesson_id: int = Field(foreign_key="lessons.id", index=True)
    resource_id: int = Field(foreign_key="resources.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
