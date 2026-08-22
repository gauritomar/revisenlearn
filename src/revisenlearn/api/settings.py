"""The settings key/value table (spec §6, §14 Settings screen)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from ..credentials import key_status
from ..db import get_session
from ..models import Setting

router = APIRouter()


class SettingsPatch(BaseModel):
    values: dict[str, object]


@router.get("/settings")
def get_settings(session: Session = Depends(get_session)) -> dict:
    rows = session.exec(select(Setting)).all()
    values = {}
    for row in rows:
        try:
            values[row.key] = json.loads(row.value_json)
        except json.JSONDecodeError:
            values[row.key] = row.value_json
    status = key_status()
    return {
        "values": values,
        # Presence and source only. The key never crosses this boundary
        # (spec §17).
        "api_key": {"present": status.present, "source": status.source},
    }


@router.patch("/settings")
def patch_settings(payload: SettingsPatch,
                   session: Session = Depends(get_session)) -> dict:
    now = datetime.now(timezone.utc)
    for key, value in payload.values.items():
        row = session.get(Setting, key)
        if row is None:
            row = Setting(key=key, value_json=json.dumps(value), updated_at=now)
        else:
            row.value_json = json.dumps(value)
            row.updated_at = now
        session.add(row)
    session.flush()
    return get_settings(session)


@router.get("/providers")
def providers() -> dict:
    """Read-only view of `config/providers.yaml` (consolidated addendum §8).

    Spec §12.2 keeps model assignment a config change, so this is shown rather
    than edited. No key material is in that file, and none is returned here.
    """
    from .. import config

    data = config.providers()
    return {
        "provider": data.get("provider", "gemini"),
        "tasks": data.get("tasks", {}),
        "embeddings": data.get("embeddings", {}),
        "source": "config/providers.yaml",
    }
