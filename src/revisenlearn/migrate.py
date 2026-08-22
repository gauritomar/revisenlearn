"""Programmatic Alembic access.

``run.sh`` calls ``alembic upgrade head`` directly; the app also calls
:func:`upgrade_to_head` on startup so that launching by any other route (tests,
``python -m revisenlearn``) can never meet a stale schema.
"""

from __future__ import annotations

import logging

from alembic import command
from alembic.config import Config

from .config import REPO_ROOT, database_url

log = logging.getLogger(__name__)


def alembic_config() -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url())
    return cfg


def upgrade_to_head() -> None:
    command.upgrade(alembic_config(), "head")
    log.info("Migrations at head")


def current_revision() -> str | None:
    from alembic.runtime.migration import MigrationContext

    from .db import get_engine

    with get_engine().connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()
