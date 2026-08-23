"""Resources — the study to-do list and the anchor for notes (spec §5).

§5.1 is the load-bearing requirement: "Adding a resource must take under five
seconds." Everything here is shaped by that. The client sends one field (a URL
or a title); subject/topic default to the last-used values, which the server
remembers so the client does not have to.
"""

from __future__ import annotations

import json
import logging
import os
import re
import webbrowser
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ..db import get_session
from ..models import (
    RESOURCE_STATUSES,
    RESOURCE_TYPES,
    Resource,
    ResourceGroup,
    Setting,
    Subtopic,
    Tag,
    Tagging,
    Topic,
)
from .schemas import (
    ResourceGroupIn,
    ResourceGroupOut,
    TagIn,
    TagOut,
    ResourceCreate,
    ResourceOut,
    ResourceUpdate,
    TitleProbe,
    TitleProbeResult,
)

log = logging.getLogger(__name__)

router = APIRouter()

LAST_USED_KEY = "last_used_placement"

#: Spec §5.1 — "one HTTP request, 3s timeout, fail silently to the raw URL."
TITLE_TIMEOUT_S = 3.0
#: A page title lives in the first few KB. Reading more of an arbitrary URL is
#: pointless and gives a hostile page a way to tie up the event loop.
TITLE_MAX_BYTES = 64 * 1024

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_WS = re.compile(r"\s+")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tags_for(session: Session, resource_id: int) -> list[dict]:
    """The tags on one resource, through the polymorphic join table."""
    rows = session.exec(
        select(Tag)
        .join(Tagging, Tagging.tag_id == Tag.id)
        .where(Tagging.target_type == "resource",
               Tagging.target_id == resource_id)
        .order_by(Tag.name)
    ).all()
    return [{"id": t.id, "name": t.name, "colour": t.colour} for t in rows]


def _out(resource: Resource, session: Session | None = None) -> ResourceOut:
    data = ResourceOut.model_validate(resource, from_attributes=True)
    if session is not None:
        data.tags = _tags_for(session, resource.id)
    return data


# --------------------------------------------------------------------------
# Type inference and title fetching
# --------------------------------------------------------------------------

def infer_resource_type(url: str | None) -> str:
    """Guess the type from the URL so the user does not have to pick one."""
    if not url:
        return "other"
    u = url.lower()
    if "youtube.com/playlist" in u or "list=" in u:
        return "youtube_playlist"
    if "youtube.com/watch" in u or "youtu.be/" in u:
        return "youtube_video"
    if "arxiv.org" in u or u.endswith(".pdf"):
        return "paper" if "arxiv.org" in u else "pdf"
    if any(d in u for d in ("leetcode.com", "hackerrank.com", "codeforces.com")):
        return "problem_set"
    if any(d in u for d in ("coursera.org", "udemy.com", "edx.org")):
        return "course"
    return "article"


def fetch_page_title(url: str) -> str | None:
    """One request, 3s, fail silently (spec §5.1).

    Every failure mode — bad scheme, DNS, timeout, non-HTML, no <title> — is a
    silent None. The caller falls back to the raw URL. This must never surface
    an error to someone who is trying to save a link in five seconds.
    """
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return None
    try:
        import httpx

        with httpx.Client(
            timeout=TITLE_TIMEOUT_S,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RevisEnLearn/0.1)"},
        ) as client:
            with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    return None
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type.lower():
                    return None
                body = b""
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) >= TITLE_MAX_BYTES or b"</title>" in body.lower():
                        break
        text = body.decode("utf-8", errors="replace")
        match = _TITLE_RE.search(text)
        if not match:
            return None
        import html

        title = _WS.sub(" ", html.unescape(match.group(1))).strip()
        return title[:300] or None
    except Exception:
        return None


@router.post("/resources/probe-title", response_model=TitleProbeResult)
def probe_title(payload: TitleProbe) -> TitleProbeResult:
    """Prefill the title field from a pasted URL, so the user can still edit it
    before saving."""
    return TitleProbeResult(
        title=fetch_page_title(payload.url),
        resource_type=infer_resource_type(payload.url),
    )


# --------------------------------------------------------------------------
# Last-used placement (spec §5.1)
# --------------------------------------------------------------------------

def _read_last_used(session: Session) -> dict:
    row = session.get(Setting, LAST_USED_KEY)
    if row is None:
        return {}
    try:
        return json.loads(row.value_json) or {}
    except json.JSONDecodeError:
        return {}


def _write_last_used(session: Session, resource: Resource) -> None:
    value = {
        "subject_id": resource.subject_id,
        "topic_id": resource.topic_id,
        "subtopic_id": resource.subtopic_id,
    }
    row = session.get(Setting, LAST_USED_KEY)
    if row is None:
        session.add(Setting(key=LAST_USED_KEY, value_json=json.dumps(value),
                            updated_at=_now()))
    else:
        row.value_json = json.dumps(value)
        row.updated_at = _now()
        session.add(row)


@router.get("/resources/last-used")
def last_used(session: Session = Depends(get_session)) -> dict:
    """What the add form should default its pickers to."""
    return _read_last_used(session)


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------

def _resolve_ancestry(session: Session, resource: Resource) -> None:
    if resource.subtopic_id and not resource.topic_id:
        st = session.get(Subtopic, resource.subtopic_id)
        if st:
            resource.topic_id = st.topic_id
    if resource.topic_id and not resource.subject_id:
        t = session.get(Topic, resource.topic_id)
        if t:
            resource.subject_id = t.subject_id


@router.get("/resources", response_model=list[ResourceOut])
def list_resources(
    status: str | None = Query(default=None),
    subject_id: int | None = Query(default=None),
    topic_id: int | None = Query(default=None),
    group_id: int | None = Query(default=None),
    ungrouped: bool = Query(default=False),
    tag: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[ResourceOut]:
    stmt = select(Resource).where(Resource.deleted_at.is_(None))
    if status is not None:
        stmt = stmt.where(Resource.status == status)
    if subject_id is not None:
        stmt = stmt.where(Resource.subject_id == subject_id)
    if topic_id is not None:
        stmt = stmt.where(Resource.topic_id == topic_id)
    if group_id is not None:
        stmt = stmt.where(Resource.group_id == group_id)
    elif ungrouped:
        stmt = stmt.where(Resource.group_id.is_(None))
    if tag:
        # Tags cut across headings, which is the point of having both.
        tagged = {
            row.target_id
            for row in session.exec(
                select(Tagging)
                .join(Tag, Tag.id == Tagging.tag_id)
                .where(Tagging.target_type == "resource",
                       Tag.name == tag)
            ).all()
        }
        stmt = stmt.where(Resource.id.in_(tagged or {-1}))
    rows = session.exec(
        stmt.order_by(Resource.priority.desc(), Resource.created_at.desc())
    ).all()
    return [_out(r, session) for r in rows]


@router.get("/resources/study-next", response_model=list[ResourceOut])
def study_next(
    limit: int = Query(default=5, ge=1, le=50),
    session: Session = Depends(get_session),
) -> list[ResourceOut]:
    """The ranked to-do for the dashboard (spec §14 "Study next").

    §10.4's priority formula governs *review items*, not resources, and the
    spec leaves this ranking open. The order is: things already started, then
    things explicitly queued as next, then the inbox; within each, higher
    priority first, then least recently touched — so a half-finished video
    outranks a fresh link, and nothing sits at the bottom forever.
    """
    rank = {"in_progress": 0, "next": 1, "inbox": 2}
    rows = session.exec(
        select(Resource).where(
            Resource.deleted_at.is_(None),
            Resource.status.in_(("in_progress", "next", "inbox")),
        )
    ).all()
    rows.sort(
        key=lambda r: (
            rank.get(r.status, 9),
            -r.priority,
            r.last_opened_at or r.created_at,
        )
    )
    return [_out(r, session) for r in rows[:limit]]


@router.post("/resources", response_model=ResourceOut, status_code=201)
def create_resource(payload: ResourceCreate,
                    session: Session = Depends(get_session)) -> ResourceOut:
    """The §5.1 fast add. Everything except one field is optional."""
    if not (payload.url or payload.title):
        raise HTTPException(400, "A url or a title is required")

    if payload.status not in RESOURCE_STATUSES:
        raise HTTPException(400, f"status must be one of {RESOURCE_STATUSES}")

    resource_type = payload.resource_type or infer_resource_type(payload.url)
    if resource_type not in RESOURCE_TYPES:
        raise HTTPException(400, f"resource_type must be one of {RESOURCE_TYPES}")

    # Fall back to the last-used placement when the client sends none.
    placement = {
        "subject_id": payload.subject_id,
        "topic_id": payload.topic_id,
        "subtopic_id": payload.subtopic_id,
    }
    if not any(placement.values()):
        placement = {**placement, **_read_last_used(session)}

    resource = Resource(
        # Fail silently to the raw URL (spec §5.1).
        title=(payload.title or "").strip() or (payload.url or "Untitled"),
        url=payload.url,
        resource_type=resource_type,
        description=payload.description,
        status=payload.status,
        priority=payload.priority,
        progress_pct=payload.progress_pct,
        progress_note=payload.progress_note,
        group_id=payload.group_id,
        **placement,
    )
    _resolve_ancestry(session, resource)
    session.add(resource)
    session.flush()
    _write_last_used(session, resource)
    return _out(resource, session)


def _get_resource(session: Session, resource_id: int) -> Resource:
    resource = session.get(Resource, resource_id)
    if resource is None or resource.deleted_at is not None:
        raise HTTPException(404, "Resource not found")
    return resource


@router.get("/resources/{resource_id}", response_model=ResourceOut)
def get_resource(resource_id: int,
                 session: Session = Depends(get_session)) -> ResourceOut:
    return _out(_get_resource(session, resource_id), session)


@router.patch("/resources/{resource_id}", response_model=ResourceOut)
def update_resource(resource_id: int, payload: ResourceUpdate,
                    session: Session = Depends(get_session)) -> ResourceOut:
    resource = _get_resource(session, resource_id)
    fields = payload.model_dump(exclude_unset=True)

    if "status" in fields and fields["status"] not in RESOURCE_STATUSES:
        raise HTTPException(400, f"status must be one of {RESOURCE_STATUSES}")
    if "resource_type" in fields and fields["resource_type"] not in RESOURCE_TYPES:
        raise HTTPException(400, f"resource_type must be one of {RESOURCE_TYPES}")

    for field, value in fields.items():
        setattr(resource, field, value)

    # Completion is a consequence of status, not a separate thing to remember.
    if fields.get("status") == "completed":
        resource.completed_at = resource.completed_at or _now()
        if "progress_pct" not in fields:
            resource.progress_pct = 100
    elif "status" in fields:
        resource.completed_at = None

    _resolve_ancestry(session, resource)
    session.add(resource)
    session.flush()
    _write_last_used(session, resource)
    return _out(resource, session)


@router.delete("/resources/{resource_id}", status_code=204)
def delete_resource(resource_id: int,
                    session: Session = Depends(get_session)) -> None:
    resource = _get_resource(session, resource_id)
    resource.deleted_at = _now()


@router.post("/resources/{resource_id}/open", response_model=ResourceOut)
def open_resource(resource_id: int,
                  session: Session = Depends(get_session)) -> ResourceOut:
    """Open the link in the *default browser* (spec §5.1), not in the app's own
    webview, and record that it was opened."""
    resource = _get_resource(session, resource_id)
    if not resource.url:
        raise HTTPException(400, "Resource has no URL")

    resource.last_opened_at = _now()
    if resource.status == "inbox":
        # Opening something is the moment it stops being an inbox item.
        resource.status = "in_progress"
    session.add(resource)
    session.flush()

    # Never hand an arbitrary scheme to the OS opener. RNL_NO_BROWSER exists so
    # the test-suite can exercise this endpoint without hijacking the user's
    # screen — the state change is still recorded either way.
    if (
        os.environ.get("RNL_NO_BROWSER") != "1"
        and re.match(r"^https?://", resource.url, re.IGNORECASE)
    ):
        webbrowser.open(resource.url)
    return _out(resource, session)


# --------------------------------------------------------------------------
# §4 Auto-detection from note content (consolidated addendum)
# --------------------------------------------------------------------------

def resource_for_url(session: Session, url: str, *, note=None) -> Resource | None:
    """Find or create the Resource for a URL written in a note.

    Addendum §4: manual entry stays exactly as it was; this is a second path
    into the *same* table. "Both creation paths … are indistinguishable once
    created — a resource doesn't 'know' which way it was added."

    Reuses `probe_title` and `infer_resource_type`, so a link typed into a note
    gets the same title fetch and type inference as one pasted into the dialog.
    """
    from ..checklist import normalise_url

    cleaned = normalise_url(url)
    if not re.match(r"^https?://", cleaned, re.IGNORECASE):
        return None

    for existing in session.exec(
        select(Resource).where(Resource.deleted_at.is_(None),
                               Resource.url.is_not(None))
    ).all():
        if normalise_url(existing.url) == cleaned:
            return existing

    # §4.4 — inherit placement from the note's lesson, then the note itself.
    placement = {"subject_id": None, "topic_id": None, "subtopic_id": None}
    if note is not None:
        placement = {
            "subject_id": note.subject_id,
            "topic_id": note.topic_id,
            "subtopic_id": note.subtopic_id,
        }
        if note.lesson_id:
            from ..models import Lesson

            lesson = session.get(Lesson, note.lesson_id)
            if lesson is not None:
                placement["topic_id"] = lesson.topic_id or placement["topic_id"]
                placement["subtopic_id"] = (lesson.subtopic_id
                                            or placement["subtopic_id"])
                topic = session.get(Topic, lesson.topic_id)
                if topic is not None:
                    placement["subject_id"] = topic.subject_id

    resource = Resource(
        title=fetch_page_title(cleaned) or cleaned,
        url=cleaned,
        resource_type=infer_resource_type(cleaned),
        status="inbox",
        **placement,
    )
    session.add(resource)
    session.flush()
    log.info("Auto-detected resource from a note: %s", resource.title)
    return resource


def detect_resources_in_note(session: Session, note_id: int) -> list[int]:
    """Scan a note's blocks for URLs and ensure a Resource exists for each.

    Returns the ids touched. Never raises: a failed title fetch or an odd URL
    must not stop a note from saving (principle §1.2 — note-taking never blocks
    on anything).
    """
    from ..checklist import first_url
    from ..models import Note, NoteBlock, NoteResourceLink

    note = session.get(Note, note_id)
    if note is None:
        return []

    blocks = session.exec(
        select(NoteBlock).where(NoteBlock.note_id == note_id,
                                NoteBlock.deleted_at.is_(None))
    ).all()

    touched: list[int] = []
    for block in blocks:
        url = block.url or first_url(block.text or "")
        if not url:
            continue
        try:
            resource = resource_for_url(session, url, note=note)
        except Exception as exc:
            log.warning("Could not auto-detect a resource from %s: %s", url, exc)
            continue
        if resource is None:
            continue
        touched.append(resource.id)

        # Addendum §2 of the lessons addendum — the many-to-many link, which
        # is what "links referenced in this note" reads from.
        already = session.exec(
            select(NoteResourceLink).where(
                NoteResourceLink.note_id == note_id,
                NoteResourceLink.resource_id == resource.id,
            )
        ).first()
        if already is None:
            session.add(NoteResourceLink(note_id=note_id,
                                         resource_id=resource.id))
    session.flush()
    return touched


# --------------------------------------------------------------------------
# Groups and tags
#
# "Add some type to resources like tags and be able to group resources under
# different headings and within each it should be able to have certain tags."
#
# A heading is where a thing is filed — one per resource, so the library has a
# shape. Tags are what it is about — many per resource, and shared across
# headings, so "interview" can cut across everything.
# --------------------------------------------------------------------------

@router.get("/resource-groups", response_model=list[ResourceGroupOut])
def list_groups(session: Session = Depends(get_session)) -> list[ResourceGroupOut]:
    groups = session.exec(
        select(ResourceGroup)
        .where(ResourceGroup.deleted_at.is_(None))
        .order_by(ResourceGroup.position, ResourceGroup.id)
    ).all()

    counts: dict[int, int] = {}
    for resource in session.exec(
        select(Resource).where(Resource.deleted_at.is_(None),
                               Resource.group_id.is_not(None))
    ).all():
        counts[resource.group_id] = counts.get(resource.group_id, 0) + 1

    return [
        ResourceGroupOut(id=g.id, name=g.name, colour=g.colour,
                         position=g.position,
                         resource_count=counts.get(g.id, 0))
        for g in groups
    ]


@router.post("/resource-groups", response_model=ResourceGroupOut, status_code=201)
def create_group(payload: ResourceGroupIn,
                 session: Session = Depends(get_session)) -> ResourceGroupOut:
    last = session.exec(
        select(ResourceGroup).where(ResourceGroup.deleted_at.is_(None))
        .order_by(ResourceGroup.position.desc())
    ).first()
    group = ResourceGroup(
        name=payload.name.strip(),
        colour=payload.colour,
        position=(payload.position if payload.position is not None
                  else ((last.position + 1) if last else 0)),
    )
    session.add(group)
    session.flush()
    return ResourceGroupOut(id=group.id, name=group.name, colour=group.colour,
                            position=group.position, resource_count=0)


@router.patch("/resource-groups/{group_id}", response_model=ResourceGroupOut)
def rename_group(group_id: int, payload: ResourceGroupIn,
                 session: Session = Depends(get_session)) -> ResourceGroupOut:
    group = session.get(ResourceGroup, group_id)
    if group is None or group.deleted_at is not None:
        raise HTTPException(404, "Group not found")
    group.name = payload.name.strip()
    if payload.colour is not None:
        group.colour = payload.colour
    if payload.position is not None:
        group.position = payload.position
    session.add(group)
    session.flush()
    return ResourceGroupOut(id=group.id, name=group.name, colour=group.colour,
                            position=group.position, resource_count=0)


@router.delete("/resource-groups/{group_id}", status_code=204)
def delete_group(group_id: int, session: Session = Depends(get_session)) -> None:
    """The heading goes; the resources under it do not.

    Deleting a shelf is not deleting the books on it — they fall back to
    ungrouped, where they can be filed again.
    """
    group = session.get(ResourceGroup, group_id)
    if group is None or group.deleted_at is not None:
        raise HTTPException(404, "Group not found")
    group.deleted_at = _now()
    session.add(group)
    for resource in session.exec(
        select(Resource).where(Resource.group_id == group_id)
    ).all():
        resource.group_id = None
        session.add(resource)


@router.get("/tags", response_model=list[TagOut])
def list_tags(session: Session = Depends(get_session)) -> list[TagOut]:
    rows = session.exec(select(Tag).order_by(Tag.name)).all()
    return [TagOut(id=t.id, name=t.name, colour=t.colour) for t in rows]


def _tag_named(session: Session, name: str, colour: str | None = None) -> Tag:
    """Get-or-create, case-insensitively: typing "Interview" twice should not
    leave two tags that look identical in a filter list."""
    cleaned = name.strip()
    for tag in session.exec(select(Tag)).all():
        if tag.name.lower() == cleaned.lower():
            return tag
    tag = Tag(name=cleaned, colour=colour)
    session.add(tag)
    session.flush()
    return tag


@router.post("/resources/{resource_id}/tags", response_model=ResourceOut)
def add_tag(resource_id: int, payload: TagIn,
            session: Session = Depends(get_session)) -> ResourceOut:
    resource = _get_resource(session, resource_id)
    tag = _tag_named(session, payload.name, payload.colour)

    already = session.exec(
        select(Tagging).where(Tagging.tag_id == tag.id,
                              Tagging.target_type == "resource",
                              Tagging.target_id == resource_id)
    ).first()
    if already is None:
        session.add(Tagging(tag_id=tag.id, target_type="resource",
                            target_id=resource_id))
        session.flush()
    return _out(resource, session)


@router.delete("/resources/{resource_id}/tags/{tag_id}", response_model=ResourceOut)
def remove_tag(resource_id: int, tag_id: int,
               session: Session = Depends(get_session)) -> ResourceOut:
    resource = _get_resource(session, resource_id)
    for row in session.exec(
        select(Tagging).where(Tagging.tag_id == tag_id,
                              Tagging.target_type == "resource",
                              Tagging.target_id == resource_id)
    ).all():
        # A tagging is a join row, not content: removing it is a real delete.
        session.delete(row)
    session.flush()
    return _out(resource, session)
