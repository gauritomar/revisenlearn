"""Resources — the study to-do list and the anchor for notes (spec §5).

§5.1 is the load-bearing requirement: "Adding a resource must take under five
seconds." Everything here is shaped by that. The client sends one field (a URL
or a title); subject/topic default to the last-used values, which the server
remembers so the client does not have to.
"""

from __future__ import annotations

import json
import os
import re
import webbrowser
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ..db import get_session
from ..models import RESOURCE_STATUSES, RESOURCE_TYPES, Resource, Setting, Subtopic, Topic
from .schemas import (
    ResourceCreate,
    ResourceOut,
    ResourceUpdate,
    TitleProbe,
    TitleProbeResult,
)

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


def _out(resource: Resource) -> ResourceOut:
    return ResourceOut.model_validate(resource, from_attributes=True)


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
    session: Session = Depends(get_session),
) -> list[ResourceOut]:
    stmt = select(Resource).where(Resource.deleted_at.is_(None))
    if status is not None:
        stmt = stmt.where(Resource.status == status)
    if subject_id is not None:
        stmt = stmt.where(Resource.subject_id == subject_id)
    if topic_id is not None:
        stmt = stmt.where(Resource.topic_id == topic_id)
    rows = session.exec(
        stmt.order_by(Resource.priority.desc(), Resource.created_at.desc())
    ).all()
    return [_out(r) for r in rows]


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
    return [_out(r) for r in rows[:limit]]


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
        **placement,
    )
    _resolve_ancestry(session, resource)
    session.add(resource)
    session.flush()
    _write_last_used(session, resource)
    return _out(resource)


def _get_resource(session: Session, resource_id: int) -> Resource:
    resource = session.get(Resource, resource_id)
    if resource is None or resource.deleted_at is not None:
        raise HTTPException(404, "Resource not found")
    return resource


@router.get("/resources/{resource_id}", response_model=ResourceOut)
def get_resource(resource_id: int,
                 session: Session = Depends(get_session)) -> ResourceOut:
    return _out(_get_resource(session, resource_id))


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
    return _out(resource)


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
    return _out(resource)
