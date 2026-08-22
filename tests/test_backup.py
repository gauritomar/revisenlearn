"""Backups (spec §17 **[LOCKED]**).

Retention deletes files, and those files are the user's insurance policy. The
selection logic is a pure function and is tested exhaustively; the deletion
path is tested for what it must *never* touch.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from conftest import REPO_ROOT, start_app


# --------------------------------------------------------------------------
# Retention policy — pure, so test it properly (spec §19)
# --------------------------------------------------------------------------

def _backups(*stamps: str):
    """Build Backup rows from 'YYYY-MM-DD HH:MM' strings."""
    from revisenlearn.backup import Backup

    return [
        Backup(
            path=Path(f"/tmp/revisenlearn-{s.replace('-', '').replace(':', '').replace(' ', '-')}.db"),
            taken_at=datetime.strptime(s, "%Y-%m-%d %H:%M"),
            size_bytes=1024,
        )
        for s in stamps
    ]


def _names(backups) -> list[str]:
    return [b.taken_at.strftime("%Y-%m-%d %H:%M") for b in backups]


def test_retention_keeps_everything_when_under_the_limit() -> None:
    from revisenlearn.backup import select_for_retention

    rows = _backups("2026-08-22 03:00", "2026-08-21 03:00", "2026-08-20 03:00")
    keep, drop = select_for_retention(rows)

    assert len(keep) == 3
    assert drop == []


def test_retention_keeps_seven_dailies() -> None:
    from revisenlearn.backup import select_for_retention

    rows = _backups(*[f"2026-08-{22 - i:02d} 03:00" for i in range(10)])
    keep, drop = select_for_retention(rows, keep_daily=7, keep_weekly=0)

    assert _names(keep) == [f"2026-08-{22 - i:02d} 03:00" for i in range(7)]
    assert len(drop) == 3


def test_several_backups_in_one_day_collapse_to_the_newest() -> None:
    """A day of pressing "Back up now" must not consume the whole daily
    window."""
    from revisenlearn.backup import select_for_retention

    rows = _backups(
        "2026-08-22 18:00", "2026-08-22 12:00", "2026-08-22 03:00",
        "2026-08-21 03:00",
    )
    keep, drop = select_for_retention(rows, keep_daily=7, keep_weekly=0)

    assert _names(keep) == ["2026-08-22 18:00", "2026-08-21 03:00"]
    assert _names(drop) == ["2026-08-22 12:00", "2026-08-22 03:00"]


def test_retention_keeps_four_weeklies_beyond_the_dailies() -> None:
    from revisenlearn.backup import select_for_retention

    # 7 consecutive days (16-22 Aug 2026), then one backup a week for 6 more
    # weeks. Each weekly falls in its own ISO week, none of them shared with
    # the daily window, so all six compete for the four weekly slots.
    daily = [f"2026-08-{22 - i:02d} 03:00" for i in range(7)]
    weekly = [
        (datetime(2026, 8, 9) - timedelta(weeks=w)).strftime("%Y-%m-%d 03:00")
        for w in range(6)
    ]
    keep, drop = select_for_retention(_backups(*daily, *weekly))

    assert len(keep) == 11
    # The four most recent weeklies survive; the two oldest go.
    assert _names(keep)[7:] == [
        "2026-08-09 03:00", "2026-08-02 03:00",
        "2026-07-26 03:00", "2026-07-19 03:00",
    ]
    assert _names(drop) == ["2026-07-12 03:00", "2026-07-05 03:00"]


def test_a_long_absence_does_not_expire_everything() -> None:
    """The window is the last 7 days *that have a backup*, not the last 7
    calendar days — otherwise coming back from a fortnight away and launching
    the app would find the history gone."""
    from revisenlearn.backup import select_for_retention

    rows = _backups(
        "2026-08-22 03:00",           # today, after the trip
        "2026-08-01 03:00", "2026-07-31 03:00", "2026-07-30 03:00",
        "2026-07-29 03:00", "2026-07-28 03:00", "2026-07-27 03:00",
    )
    keep, drop = select_for_retention(rows)

    assert len(keep) == 7
    assert drop == []


def test_retention_on_an_empty_list_is_a_no_op() -> None:
    from revisenlearn.backup import select_for_retention

    assert select_for_retention([]) == ([], [])


# --------------------------------------------------------------------------
# The nightly trigger
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "now,expected",
    [
        ("2026-08-22 03:00", "2026-08-22 03:00"),   # exactly on the boundary
        ("2026-08-22 09:15", "2026-08-22 03:00"),
        ("2026-08-22 02:59", "2026-08-21 03:00"),   # before it, so yesterday's
        ("2026-08-22 00:01", "2026-08-21 03:00"),
    ],
)
def test_nightly_boundary(now: str, expected: str) -> None:
    from revisenlearn.backup import last_nightly_boundary

    result = last_nightly_boundary(datetime.strptime(now, "%Y-%m-%d %H:%M"))
    assert result == datetime.strptime(expected, "%Y-%m-%d %H:%M")


def test_nightly_is_due_only_once_per_night(tmp_path: Path, monkeypatch) -> None:
    from revisenlearn import backup as bk
    from revisenlearn import config

    monkeypatch.setenv("RNL_DATA_DIR", str(tmp_path))
    config.load_yaml.cache_clear()

    # No backups at all -> due.
    assert bk.is_nightly_due(datetime(2026, 8, 22, 9, 0)) is True

    # One taken after last night's 03:00 -> not due again today.
    (config.backups_dir() / "revisenlearn-20260822-031500.db").write_bytes(b"x")
    assert bk.is_nightly_due(datetime(2026, 8, 22, 9, 0)) is False

    # Next morning, past 03:00 -> due again.
    assert bk.is_nightly_due(datetime(2026, 8, 23, 9, 0)) is True
    # ...but not at 02:00, which is still the same night.
    assert bk.is_nightly_due(datetime(2026, 8, 23, 2, 0)) is False


# --------------------------------------------------------------------------
# Taking a real backup
# --------------------------------------------------------------------------

def test_backup_now_writes_a_usable_database(app, client) -> None:
    """The whole point: the copy must open and contain the data."""
    subject = client.post("/api/subjects", json={"name": "GenAI"}).json()
    topic = client.post(
        "/api/topics", json={"subject_id": subject["id"], "name": "Retrieval"}
    ).json()
    subtopic = client.post(
        "/api/subtopics", json={"topic_id": topic["id"], "name": "Hybrid search"}
    ).json()
    note = client.post(
        "/api/notes/ensure", json={"subtopic_id": subtopic["id"]}
    ).json()
    client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [{"id": None, "position": 0, "block_type": "paragraph",
                          "text": "Text that must survive"}]},
    )

    result = client.post("/api/backup/now").json()

    path = Path(result["created"]["path"])
    assert path.exists()
    assert result["created"]["size_bytes"] > 0

    # Open the copy independently and read the data back out.
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT name FROM subjects").fetchall() == [("GenAI",)]
        assert conn.execute(
            "SELECT text FROM note_blocks WHERE deleted_at IS NULL"
        ).fetchall() == [("Text that must survive",)]
    finally:
        conn.close()


def test_backup_list_reports_what_is_on_disk(app, client) -> None:
    assert client.get("/api/backup/list").json()["backups"] == []

    first = client.post("/api/backup/now").json()["created"]
    listing = client.get("/api/backup/list").json()

    assert [b["name"] for b in listing["backups"]] == [first["name"]]
    assert listing["total_bytes"] == first["size_bytes"]
    assert listing["directory"].endswith("backups")


def test_backups_are_named_by_timestamp(app, client) -> None:
    import re

    name = client.post("/api/backup/now").json()["created"]["name"]
    assert re.fullmatch(r"revisenlearn-\d{8}-\d{6}\.db", name), name


# --------------------------------------------------------------------------
# What pruning must never do
# --------------------------------------------------------------------------

def test_prune_never_touches_files_it_did_not_create(tmp_path: Path,
                                                     monkeypatch) -> None:
    """The backups directory is inside the user's data directory. Anything not
    matching our own naming pattern is none of our business."""
    from revisenlearn import backup as bk
    from revisenlearn import config

    monkeypatch.setenv("RNL_DATA_DIR", str(tmp_path))
    backups = config.backups_dir()

    # Enough of ours to force a prune.
    for day in range(1, 20):
        (backups / f"revisenlearn-202608{day:02d}-030000.db").write_bytes(b"x")

    strangers = [
        backups / "notes-i-saved-here.txt",
        backups / "revisenlearn.db",              # no timestamp
        backups / "revisenlearn-2026-08-22.db",   # wrong stamp format
        backups / "backup.db",
    ]
    for path in strangers:
        path.write_bytes(b"precious")

    bk.prune_backups()

    for path in strangers:
        assert path.exists(), f"prune deleted {path.name}"
        assert path.read_bytes() == b"precious"


def test_prune_never_deletes_the_backup_just_taken(tmp_path: Path,
                                                   monkeypatch) -> None:
    """A fresh backup must survive its own prune, whatever the policy says."""
    from revisenlearn import backup as bk
    from revisenlearn import config

    monkeypatch.setenv("RNL_DATA_DIR", str(tmp_path))
    backups = config.backups_dir()
    for day in range(1, 25):
        (backups / f"revisenlearn-202608{day:02d}-030000.db").write_bytes(b"x")

    # An artificially old "new" backup, which retention would otherwise drop.
    fresh = bk.Backup(
        path=backups / "revisenlearn-20250101-000000.db",
        taken_at=datetime(2025, 1, 1),
        size_bytes=1,
    )
    fresh.path.write_bytes(b"x")

    bk.prune_backups(protect=fresh)
    assert fresh.path.exists()


def test_backup_now_applies_retention(tmp_path: Path, monkeypatch) -> None:
    from revisenlearn import backup as bk
    from revisenlearn import config

    monkeypatch.setenv("RNL_DATA_DIR", str(tmp_path))
    backups = config.backups_dir()
    # 30 consecutive daily backups, well past 7 daily + 4 weekly.
    for day in range(1, 31):
        (backups / f"revisenlearn-202607{day:02d}-030000.db").write_bytes(b"x")

    assert len(bk.list_backups()) == 30
    deleted = bk.prune_backups()

    remaining = bk.list_backups()
    # 7 dailies (24-30 Jul) plus 3 weeklies, not 4: the daily window already
    # covers two ISO weeks, and 1-23 Jul only spans three further ones, so
    # there is no fourth week left to keep. 7 + 3 = 10.
    assert len(remaining) == 10, [b.name for b in remaining]
    assert len(deleted) == 20
    # The seven newest days survive.
    assert [b.taken_at.day for b in remaining[:7]] == [30, 29, 28, 27, 26, 25, 24]
    # And exactly one backup survives from each remaining ISO week.
    weeks = [b.taken_at.isocalendar()[:2] for b in remaining]
    assert len(weeks) == len(set(weeks)) + 5  # the 7 dailies share 2 weeks


def test_a_second_backup_in_the_same_second_is_refused(tmp_path: Path,
                                                       monkeypatch) -> None:
    """Never silently overwrite an existing backup."""
    from revisenlearn import backup as bk
    from revisenlearn import config

    monkeypatch.setenv("RNL_DATA_DIR", str(tmp_path))
    now = datetime(2026, 8, 22, 3, 0, 0)
    (config.backups_dir() / "revisenlearn-20260822-030000.db").write_bytes(b"x")

    with pytest.raises(FileExistsError):
        bk.create_backup(now)


# --------------------------------------------------------------------------
# Nightly on startup, end to end
# --------------------------------------------------------------------------

def test_nightly_backup_runs_on_first_launch(db_path: Path) -> None:
    """Spec §17 — "nightly at first launch after 03:00"."""
    instance = start_app(db_path, extra_env={"RNL_NO_NIGHTLY_BACKUP": "0"})
    try:
        import httpx

        with httpx.Client(base_url=instance.base_url, timeout=30) as c:
            listing = c.get("/api/backup/list").json()
        # Startup with an empty backups directory always takes one.
        assert len(listing["backups"]) == 1
    finally:
        instance.stop()


def test_nightly_backup_does_not_run_twice_the_same_night(db_path: Path) -> None:
    first = start_app(db_path, extra_env={"RNL_NO_NIGHTLY_BACKUP": "0"})
    import httpx

    try:
        with httpx.Client(base_url=first.base_url, timeout=30) as c:
            after_first = c.get("/api/backup/list").json()["backups"]
        assert len(after_first) == 1
    finally:
        first.stop()

    second = start_app(db_path, extra_env={"RNL_NO_NIGHTLY_BACKUP": "0"})
    try:
        with httpx.Client(base_url=second.base_url, timeout=30) as c:
            after_second = c.get("/api/backup/list").json()["backups"]
        assert [b["name"] for b in after_second] == [b["name"] for b in after_first]
    finally:
        second.stop()


def test_a_failing_backup_does_not_stop_the_app_starting(tmp_path: Path) -> None:
    """Spec §16/§17 — the app must still open. A read-only backups directory is
    the realistic version of this."""
    data_dir = tmp_path / "data"
    (data_dir / "backups").mkdir(parents=True)
    (data_dir / "backups").chmod(0o500)  # readable, not writable

    db = tmp_path / "app.db"
    env = {
        **os.environ,
        "RNL_DB_PATH": str(db),
        "RNL_DATA_DIR": str(data_dir),
        "RNL_SEED_SUBJECTS": "0",
        "RNL_NO_NIGHTLY_BACKUP": "0",
    }
    try:
        out = subprocess.run(
            [sys.executable, "-c",
             "from revisenlearn.backup import run_nightly_if_due;"
             "print('result:', run_nightly_if_due())"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
        )
        assert out.returncode == 0, out.stderr
        assert "result: None" in out.stdout
    finally:
        (data_dir / "backups").chmod(0o700)
