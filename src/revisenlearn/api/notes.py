"""Notes and the writing surface (spec §4).

Note-taking never blocks on anything (principle §1.2): a block save is a single
short transaction against local SQLite plus an FTS index update. No network, no
LLM, no pipeline stage sits in this path.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ..db import get_session, reindex_block
from ..hashing import content_hash
from ..models import Note, NoteBlock, Subject, Subtopic, Topic
from .schemas import BlockOut, BlocksSave, NoteCreate, NoteOut, NoteUpdate

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _block_state(block: NoteBlock) -> str:
    """The §4.2 processed-state indicator."""
    if block.processed_hash is None:
        return "unprocessed"
    if block.processed_hash == block.content_hash:
        return "processed"
    return "stale"


def _block_out(block: NoteBlock) -> BlockOut:
    return BlockOut(
        id=block.id,
        note_id=block.note_id,
        position=block.position,
        block_type=block.block_type,
        text=block.text,
        content_hash=block.content_hash,
        processed_hash=block.processed_hash,
        state=_block_state(block),
    )


def _load_blocks(session: Session, note_id: int) -> list[NoteBlock]:
    return list(
        session.exec(
            select(NoteBlock)
            .where(NoteBlock.note_id == note_id, NoteBlock.deleted_at.is_(None))
            .order_by(NoteBlock.position, NoteBlock.id)
        ).all()
    )


def _note_out(session: Session, note: Note) -> NoteOut:
    blocks = _load_blocks(session, note.id)
    states = [_block_state(b) for b in blocks]
    return NoteOut(
        id=note.id,
        title=note.title,
        study_date=note.study_date,
        subject_id=note.subject_id,
        topic_id=note.topic_id,
        subtopic_id=note.subtopic_id,
        resource_id=note.resource_id,
        created_at=note.created_at,
        updated_at=note.updated_at,
        blocks=[_block_out(b) for b in blocks],
        counts={
            "processed": states.count("processed"),
            "new": states.count("unprocessed"),
            "edited": states.count("stale"),
        },
    )


def _resolve_ancestry(session: Session, note: Note) -> None:
    """Denormalise subject/topic from the subtopic so notes are queryable by
    any level of the hierarchy without a join chain."""
    if note.subtopic_id and not note.topic_id:
        subtopic = session.get(Subtopic, note.subtopic_id)
        if subtopic:
            note.topic_id = subtopic.topic_id
    if note.topic_id and not note.subject_id:
        topic = session.get(Topic, note.topic_id)
        if topic:
            note.subject_id = topic.subject_id


def _default_title(session: Session, note: Note) -> str:
    """A note is titled after its subtopic (spec §3's example: the note for
    "Hybrid search" is called "Hybrid search")."""
    if note.subtopic_id:
        st = session.get(Subtopic, note.subtopic_id)
        if st:
            return st.name
    if note.topic_id:
        t = session.get(Topic, note.topic_id)
        if t:
            return t.name
    if note.subject_id:
        s = session.get(Subject, note.subject_id)
        if s:
            return s.name
    return note.study_date.isoformat()


# --- Collection ------------------------------------------------------------

@router.get("/notes", response_model=list[NoteOut])
def list_notes(
    subtopic_id: int | None = Query(default=None),
    topic_id: int | None = Query(default=None),
    subject_id: int | None = Query(default=None),
    study_date: date_cls | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[NoteOut]:
    stmt = select(Note).where(Note.deleted_at.is_(None))
    if subtopic_id is not None:
        stmt = stmt.where(Note.subtopic_id == subtopic_id)
    if topic_id is not None:
        stmt = stmt.where(Note.topic_id == topic_id)
    if subject_id is not None:
        stmt = stmt.where(Note.subject_id == subject_id)
    if study_date is not None:
        stmt = stmt.where(Note.study_date == study_date)
    notes = session.exec(stmt.order_by(Note.study_date.desc(), Note.id.desc())).all()
    return [_note_out(session, n) for n in notes]


@router.post("/notes", response_model=NoteOut, status_code=201)
def create_note(payload: NoteCreate,
                session: Session = Depends(get_session)) -> NoteOut:
    note = Note(
        title=payload.title or "",
        study_date=payload.study_date or date_cls.today(),
        subject_id=payload.subject_id,
        topic_id=payload.topic_id,
        subtopic_id=payload.subtopic_id,
        resource_id=payload.resource_id,
    )
    _resolve_ancestry(session, note)
    if not note.title:
        note.title = _default_title(session, note)
    session.add(note)
    session.flush()
    return _note_out(session, note)


@router.post("/notes/ensure", response_model=NoteOut)
def ensure_note(payload: NoteCreate,
                session: Session = Depends(get_session)) -> NoteOut:
    """Get-or-create the note for a (subtopic, day).

    Spec §4.1: "One note per (Subtopic, day) by default". Clicking a subtopic in
    the sidebar opens today's note, creating it on the spot if it does not
    exist — the same move §5.1 describes for resources.
    """
    study_date = payload.study_date or date_cls.today()
    stmt = select(Note).where(
        Note.deleted_at.is_(None),
        Note.study_date == study_date,
        Note.resource_id.is_(None),
    )
    if payload.subtopic_id is not None:
        stmt = stmt.where(Note.subtopic_id == payload.subtopic_id)
    elif payload.topic_id is not None:
        stmt = stmt.where(Note.topic_id == payload.topic_id,
                          Note.subtopic_id.is_(None))
    else:
        raise HTTPException(400, "subtopic_id or topic_id is required")

    existing = session.exec(stmt.order_by(Note.id)).first()
    if existing is not None:
        return _note_out(session, existing)
    return create_note(payload.model_copy(update={"study_date": study_date}), session)


@router.get("/notes/by-date/{study_date}", response_model=list[NoteOut])
def notes_by_date(study_date: date_cls,
                  session: Session = Depends(get_session)) -> list[NoteOut]:
    notes = session.exec(
        select(Note)
        .where(Note.deleted_at.is_(None), Note.study_date == study_date)
        .order_by(Note.id)
    ).all()
    return [_note_out(session, n) for n in notes]


# --- Single note -----------------------------------------------------------

def _get_note(session: Session, note_id: int) -> Note:
    note = session.get(Note, note_id)
    if note is None or note.deleted_at is not None:
        raise HTTPException(404, "Note not found")
    return note


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: int, session: Session = Depends(get_session)) -> NoteOut:
    return _note_out(session, _get_note(session, note_id))


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(note_id: int, payload: NoteUpdate,
                session: Session = Depends(get_session)) -> NoteOut:
    note = _get_note(session, note_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(note, field, value)
    note.updated_at = _now()
    session.add(note)
    session.flush()
    return _note_out(session, note)


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, session: Session = Depends(get_session)) -> None:
    note = _get_note(session, note_id)
    now = _now()
    note.deleted_at = now
    for block in _load_blocks(session, note_id):
        block.deleted_at = now
        session.flush()
        reindex_block(session, block)


# --- Blocks ----------------------------------------------------------------

@router.get("/notes/{note_id}/blocks", response_model=list[BlockOut])
def get_blocks(note_id: int,
               session: Session = Depends(get_session)) -> list[BlockOut]:
    _get_note(session, note_id)
    return [_block_out(b) for b in _load_blocks(session, note_id)]


@router.put("/notes/{note_id}/blocks", response_model=NoteOut)
def save_blocks(note_id: int, payload: BlocksSave,
                session: Session = Depends(get_session)) -> NoteOut:
    """Autosave. Writes the full block list for the note (spec §4.1).

    ``processed_hash`` is preserved across a save so that editing a processed
    block flips it to the amber "stale" state rather than losing the fact that
    it was ever processed (spec §4.2).
    """
    note = _get_note(session, note_id)
    existing = {b.id: b for b in _load_blocks(session, note_id)}
    seen: set[int] = set()

    for incoming in payload.blocks:
        new_hash = content_hash(incoming.text)
        block = existing.get(incoming.id) if incoming.id is not None else None
        if block is None:
            block = NoteBlock(
                note_id=note_id,
                position=incoming.position,
                block_type=incoming.block_type,
                text=incoming.text,
                content_hash=new_hash,
            )
            session.add(block)
            session.flush()
        else:
            block.position = incoming.position
            block.block_type = incoming.block_type
            block.text = incoming.text
            block.content_hash = new_hash
            block.updated_at = _now()
            session.add(block)
            session.flush()
        seen.add(block.id)
        reindex_block(session, block)

    # Blocks the client no longer sends were deleted in the editor. Soft-delete
    # them — nothing is ever hard-deleted (principle §1.7).
    now = _now()
    for block_id, block in existing.items():
        if block_id not in seen:
            block.deleted_at = now
            session.add(block)
            session.flush()
            reindex_block(session, block)

    note.updated_at = now
    session.add(note)
    session.flush()
    return _note_out(session, note)
