"""Markdown export (spec §17 **[LOCKED]**).

"Export all notes as Markdown — one folder per Subject/Topic/Subtopic, one file
per note, front-matter with date and resource. This is the real insurance
policy against the app itself."

So the output must be readable with no tooling at all: plain directories, plain
files, YAML front-matter, and Markdown that renders anywhere. Nothing here
depends on the app being able to run.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from . import config
from .models import Note, NoteBlock, Resource, Subject, Subtopic, Topic

log = logging.getLogger(__name__)

STAMP_FMT = "%Y%m%d-%H%M%S"

#: Characters that are illegal or hostile in a path component on macOS,
#: Windows or a zip. The user names their own subjects, so this has to hold.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DOTS = re.compile(r"^\.+|\.+$")
_WS = re.compile(r"\s+")

#: Windows reserves these, and a folder named CON is a bad surprise to hit
#: years later when restoring on another machine.
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_component(name: str, fallback: str = "untitled") -> str:
    """Turn a user-chosen name into a safe single path component."""
    cleaned = _ILLEGAL.sub("-", name or "")
    cleaned = _WS.sub(" ", cleaned).strip()
    cleaned = _DOTS.sub("", cleaned).strip()
    if not cleaned:
        return fallback
    if cleaned.upper() in _RESERVED:
        cleaned = f"{cleaned}-"
    # Leave room for a date prefix and the .md suffix inside a 255-byte limit.
    return cleaned[:120]


@dataclass(frozen=True)
class ExportResult:
    path: Path
    note_count: int
    file_count: int

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "note_count": self.note_count,
            "file_count": self.file_count,
        }


# --------------------------------------------------------------------------
# Block rendering
# --------------------------------------------------------------------------

def render_blocks(blocks: list[NoteBlock]) -> str:
    """Render a note's blocks as Markdown.

    Consecutive list items are emitted as one list; numbered lists count up.
    A block that has been through the pipeline and then been edited carries no
    marker here — the export is the user's text, not the app's bookkeeping.

    Each block renders to exactly one *chunk*, which may itself span several
    lines (a fenced code block, a multi-line quote). Keeping the chunk as the
    unit is what lets the spacing pass below stay aligned with `blocks`.
    """
    chunks: list[tuple[str, str]] = []   # (block_type, rendered chunk)
    ordinal = 0

    for block in blocks:
        kind = block.block_type
        text = (block.text or "").rstrip()

        if kind != "numbered_list_item":
            ordinal = 0

        if kind == "heading1":
            chunk = f"# {text}"
        elif kind == "heading2":
            chunk = f"## {text}"
        elif kind == "heading3":
            chunk = f"### {text}"
        elif kind == "bullet_list_item":
            chunk = f"- {text}"
        elif kind == "numbered_list_item":
            ordinal += 1
            chunk = f"{ordinal}. {text}"
        elif kind == "quote":
            chunk = "\n".join(f"> {line}" for line in text.split("\n"))
        elif kind == "code_block":
            # Fence longer than any run of backticks inside, so code containing
            # a fence still round-trips.
            longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
            fence = "`" * max(3, longest + 1)
            chunk = f"{fence}\n{text}\n{fence}"
        elif kind == "divider":
            chunk = "---"
        else:
            chunk = text

        chunks.append((kind, chunk))

    # Blank line between blocks, except within a run of list items, where a
    # blank line would split one list into several in most renderers.
    out: list[str] = []
    previous_kind: str | None = None
    for kind, chunk in chunks:
        same_list = (
            kind in ("bullet_list_item", "numbered_list_item")
            and kind == previous_kind
        )
        if out and not same_list:
            out.append("")
        out.append(chunk)
        previous_kind = kind

    return "\n".join(out).strip() + "\n"


def _yaml_scalar(value: object) -> str:
    """Quote a front-matter value so the YAML always parses back."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_front_matter(fields: dict[str, object]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

def export_markdown(
    session: Session,
    destination: Path | None = None,
    now: datetime | None = None,
) -> ExportResult:
    """Write every non-deleted note to ``destination``.

    Layout (spec §17): one folder per Subject/Topic/Subtopic, one file per note.
    A note with no subject lands in ``_unfiled``; the point of an insurance
    policy is that nothing is dropped for being untidy.
    """
    now = now or datetime.now()
    root = destination or (
        config.data_dir() / "exports" / f"export-{now.strftime(STAMP_FMT)}"
    )
    root.mkdir(parents=True, exist_ok=True)

    subjects = {s.id: s for s in session.exec(select(Subject)).all()}
    topics = {t.id: t for t in session.exec(select(Topic)).all()}
    subtopics = {s.id: s for s in session.exec(select(Subtopic)).all()}
    resources = {r.id: r for r in session.exec(select(Resource)).all()}

    notes = session.exec(
        select(Note)
        .where(Note.deleted_at.is_(None))
        .order_by(Note.study_date, Note.id)
    ).all()

    used: set[Path] = set()
    file_count = 0

    for note in notes:
        blocks = list(
            session.exec(
                select(NoteBlock)
                .where(NoteBlock.note_id == note.id,
                       NoteBlock.deleted_at.is_(None))
                .order_by(NoteBlock.position, NoteBlock.id)
            ).all()
        )

        subject = subjects.get(note.subject_id) if note.subject_id else None
        topic = topics.get(note.topic_id) if note.topic_id else None
        subtopic = subtopics.get(note.subtopic_id) if note.subtopic_id else None
        resource = resources.get(note.resource_id) if note.resource_id else None

        folder = root
        if subject is None:
            folder = folder / "_unfiled"
        else:
            folder = folder / safe_component(subject.name, "subject")
            if topic is not None:
                folder = folder / safe_component(topic.name, "topic")
                if subtopic is not None:
                    folder = folder / safe_component(subtopic.name, "subtopic")
        folder.mkdir(parents=True, exist_ok=True)

        stem = f"{note.study_date.isoformat()}-{safe_component(note.title, 'note')}"
        path = folder / f"{stem}.md"
        # Two notes for the same subtopic and day are allowed (§4.1), and they
        # may share a title. Disambiguate rather than overwrite.
        suffix = 2
        while path in used or path.exists():
            path = folder / f"{stem}-{suffix}.md"
            suffix += 1
        used.add(path)

        front = {
            "title": note.title,
            "date": note.study_date.isoformat(),
            "subject": subject.name if subject else None,
            "topic": topic.name if topic else None,
            "subtopic": subtopic.name if subtopic else None,
            "resource": resource.title if resource else None,
            "resource_url": resource.url if resource else None,
            "created_at": note.created_at.isoformat() if note.created_at else None,
            "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        }

        body = render_blocks(blocks) if blocks else ""
        path.write_text(render_front_matter(front) + body, encoding="utf-8")
        file_count += 1

    _write_index(root, len(notes), file_count, now)

    log.info("Exported %s notes to %s", file_count, root)
    return ExportResult(path=root, note_count=len(notes), file_count=file_count)


def _write_index(root: Path, note_count: int, file_count: int,
                 now: datetime) -> None:
    """A README so the folder explains itself years from now, on a machine that
    has never heard of this app."""
    (root / "README.md").write_text(
        "# Revise & Learn — notes export\n\n"
        f"Exported {now.strftime('%Y-%m-%d %H:%M:%S')}.\n\n"
        f"{file_count} file(s) from {note_count} note(s).\n\n"
        "One folder per Subject / Topic / Subtopic, one Markdown file per note.\n"
        "Each file starts with YAML front-matter giving its date and, where the\n"
        "note was written against a resource, that resource's title and URL.\n"
        "Notes with no subject are under `_unfiled/`.\n\n"
        "These are plain files. Nothing here needs the app to read it.\n",
        encoding="utf-8",
    )
