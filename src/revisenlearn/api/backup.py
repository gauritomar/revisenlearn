"""Backup and export endpoints (spec §15, §17)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from .. import backup as backup_service
from .. import config
from ..db import get_session
from ..export import export_markdown

router = APIRouter()


class BackupOut(BaseModel):
    name: str
    path: str
    taken_at: str
    size_bytes: int


class BackupRunResult(BaseModel):
    created: BackupOut
    #: What retention removed as a consequence of this run, so the Settings
    #: screen can say so rather than quietly shrinking the list.
    pruned: list[str] = []


class BackupListResult(BaseModel):
    directory: str
    backups: list[BackupOut]
    total_bytes: int


class ExportRequest(BaseModel):
    #: Optional absolute destination. Defaults to
    #: ``~/.revisenlearn/exports/export-<timestamp>``.
    destination: str | None = None


class ExportResultOut(BaseModel):
    path: str
    note_count: int
    file_count: int


@router.post("/backup/now", response_model=BackupRunResult)
def backup_now() -> BackupRunResult:
    """Spec §17 — the manual "Back up now" button in Settings."""
    try:
        created, deleted = backup_service.backup_now()
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from None
    except OSError as exc:
        raise HTTPException(500, f"Backup failed: {exc}") from None
    return BackupRunResult(
        created=BackupOut(**created.as_dict()),
        pruned=[b.name for b in deleted],
    )


@router.get("/backup/list", response_model=BackupListResult)
def backup_list() -> BackupListResult:
    backups = backup_service.list_backups()
    return BackupListResult(
        directory=str(config.backups_dir()),
        backups=[BackupOut(**b.as_dict()) for b in backups],
        total_bytes=sum(b.size_bytes for b in backups),
    )


@router.post("/export/markdown", response_model=ExportResultOut)
def export_notes_markdown(
    payload: ExportRequest | None = None,
    session: Session = Depends(get_session),
) -> ExportResultOut:
    """Spec §17 — "the real insurance policy against the app itself"."""
    destination: Path | None = None
    if payload and payload.destination:
        destination = Path(payload.destination).expanduser()
        if not destination.is_absolute():
            raise HTTPException(400, "destination must be an absolute path")

    try:
        result = export_markdown(session, destination)
    except OSError as exc:
        raise HTTPException(500, f"Export failed: {exc}") from None
    return ExportResultOut(**result.as_dict())
