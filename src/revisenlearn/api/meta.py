"""Health and app metadata."""

from __future__ import annotations

from fastapi import APIRouter

from .. import __version__
from ..credentials import key_status

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/meta")
def meta() -> dict:
    """Everything the shell needs at boot.

    ``api_key`` reports presence and source only — never the key itself
    (spec §17).
    """
    status = key_status()
    return {
        "app_name": "Revise & Learn",
        "version": __version__,
        "phase": 7,
        "api_key": {"present": status.present, "source": status.source},
    }
