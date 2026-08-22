"""Backups (spec §17 **[LOCKED]**).

- Nightly at first launch after 03:00: ``VACUUM INTO`` a timestamped copy in
  ``~/.revisenlearn/backups/``.
- Retain 7 daily + 4 weekly.
- Manual "Back up now" button in Settings.

``VACUUM INTO`` is the right primitive here: it writes a consistent, compacted
copy of the database from inside SQLite, so it is safe against concurrent
readers and cannot capture a half-written page the way ``cp`` can.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from . import config
from .db import get_engine, write_lock

log = logging.getLogger(__name__)

#: ``revisenlearn-20260822-031500.db``. Retention only ever considers files
#: matching this exactly — a stray file in the backups directory, or something
#: the user put there themselves, is never deleted.
BACKUP_GLOB = "revisenlearn-*.db"
BACKUP_RE = re.compile(r"^revisenlearn-(\d{8})-(\d{6})\.db$")
STAMP_FMT = "%Y%m%d-%H%M%S"

#: Spec §17 — nightly at first launch after 03:00.
NIGHTLY_HOUR = 3
#: Spec §17 — retain 7 daily + 4 weekly.
KEEP_DAILY = 7
KEEP_WEEKLY = 4


@dataclass(frozen=True)
class Backup:
    path: Path
    taken_at: datetime
    size_bytes: int

    @property
    def name(self) -> str:
        return self.path.name

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "taken_at": self.taken_at.isoformat(),
            "size_bytes": self.size_bytes,
        }


def _parse(path: Path) -> datetime | None:
    match = BACKUP_RE.match(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(f"{match.group(1)}-{match.group(2)}", STAMP_FMT)
    except ValueError:
        return None


def list_backups() -> list[Backup]:
    """Newest first."""
    out: list[Backup] = []
    for path in config.backups_dir().glob(BACKUP_GLOB):
        taken_at = _parse(path)
        if taken_at is None or not path.is_file():
            continue
        out.append(Backup(path=path, taken_at=taken_at,
                          size_bytes=path.stat().st_size))
    return sorted(out, key=lambda b: b.taken_at, reverse=True)


def _quote_sql_path(path: Path) -> str:
    """SQLite has no parameter binding for VACUUM INTO's target, so the path is
    inlined. Doubling single quotes is the correct escape for a SQL string
    literal, and the path is ours, not user input."""
    return "'" + str(path).replace("'", "''") + "'"


def create_backup(now: datetime | None = None) -> Backup:
    """``VACUUM INTO`` a timestamped copy. Returns the new backup."""
    now = now or datetime.now()
    target = config.backups_dir() / f"revisenlearn-{now.strftime(STAMP_FMT)}.db"

    if target.exists():
        # Two backups inside the same second. Never silently overwrite one.
        raise FileExistsError(f"A backup already exists at {target}")

    # The pipeline worker holds longer write transactions; serialise against it.
    with write_lock:
        engine = get_engine()
        # VACUUM cannot run inside a transaction.
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql(f"VACUUM INTO {_quote_sql_path(target)}")

    backup = Backup(path=target, taken_at=now, size_bytes=target.stat().st_size)
    log.info("Backup written: %s (%.1f MB)", backup.name,
             backup.size_bytes / 1_048_576)
    return backup


def select_for_retention(
    backups: list[Backup],
    keep_daily: int = KEEP_DAILY,
    keep_weekly: int = KEEP_WEEKLY,
) -> tuple[list[Backup], list[Backup]]:
    """Split into ``(keep, drop)`` for a 7-daily + 4-weekly policy.

    Kept:
      * the most recent backup of each of the last ``keep_daily`` *days that
        have a backup* — not the last 7 calendar days, so a week away from the
        machine does not silently expire the lot;
      * then the most recent backup of each of the next ``keep_weekly`` ISO
        weeks that have one, skipping weeks already covered by a daily.

    Everything else is dropped. Same-day extras (several manual backups in one
    day) collapse to the newest for that day.
    """
    if not backups:
        return [], []

    ordered = sorted(backups, key=lambda b: b.taken_at, reverse=True)

    newest_per_day: dict[tuple, Backup] = {}
    for backup in ordered:
        newest_per_day.setdefault(backup.taken_at.date(), backup)

    daily_days = sorted(newest_per_day, reverse=True)[:keep_daily]
    keep = {id(newest_per_day[d]) for d in daily_days}
    covered_weeks = {d.isocalendar()[:2] for d in daily_days}

    newest_per_week: dict[tuple, Backup] = {}
    for backup in ordered:
        week = backup.taken_at.isocalendar()[:2]
        if week in covered_weeks:
            continue
        newest_per_week.setdefault(week, backup)

    for week in sorted(newest_per_week, reverse=True)[:keep_weekly]:
        keep.add(id(newest_per_week[week]))

    kept = [b for b in ordered if id(b) in keep]
    dropped = [b for b in ordered if id(b) not in keep]
    return kept, dropped


def prune_backups(protect: Backup | None = None) -> list[Backup]:
    """Apply the retention policy. Returns what was deleted.

    ``protect`` is never deleted — a freshly taken backup must survive its own
    prune even if the clock or the policy would say otherwise.
    """
    _, dropped = select_for_retention(list_backups())
    deleted: list[Backup] = []
    for backup in dropped:
        if protect is not None and backup.path == protect.path:
            continue
        try:
            backup.path.unlink()
            deleted.append(backup)
        except OSError as exc:
            log.warning("Could not remove old backup %s: %s", backup.name, exc)
    if deleted:
        log.info("Pruned %s old backup(s)", len(deleted))
    return deleted


def backup_now(now: datetime | None = None) -> tuple[Backup, list[Backup]]:
    """Take a backup and apply retention. Returns ``(created, deleted)``."""
    created = create_backup(now)
    deleted = prune_backups(protect=created)
    return created, deleted


# --------------------------------------------------------------------------
# The nightly run
# --------------------------------------------------------------------------

def last_nightly_boundary(now: datetime) -> datetime:
    """The most recent 03:00 that has already passed."""
    today_at_three = datetime.combine(now.date(), time(hour=NIGHTLY_HOUR))
    if now >= today_at_three:
        return today_at_three
    return today_at_three - timedelta(days=1)


def is_nightly_due(now: datetime | None = None) -> bool:
    """True when no backup has been taken since the last 03:00 boundary.

    Spec §17 says "nightly at *first launch* after 03:00" — the app is not a
    daemon, so this is checked on startup rather than scheduled.
    """
    now = now or datetime.now()
    boundary = last_nightly_boundary(now)
    backups = list_backups()
    if not backups:
        return True
    return backups[0].taken_at < boundary


def run_nightly_if_due(now: datetime | None = None) -> Backup | None:
    """Called on startup. Never raises — a failed backup must not stop the app
    from opening, but it must be loud in the log."""
    if os.environ.get("RNL_NO_NIGHTLY_BACKUP") == "1":
        return None
    try:
        if not is_nightly_due(now):
            return None
        created, _ = backup_now(now)
        return created
    except Exception:
        log.exception("Nightly backup failed")
        return None
