"""First-run seeding: the settings table and a starter subject tree.

Spec §18 Phase 1 is *done when* "the window opens, the sidebar renders seeded
subjects, migrations run clean" — so a fresh database gets a small subject tree.
Set ``RNL_SEED_SUBJECTS=0`` to skip that (the test-suite does, so each workflow
starts from a genuinely empty tree).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from sqlmodel import Session, select

from .models import Setting, Subject, Subtopic, Topic

log = logging.getLogger(__name__)

#: Seeded from spec §12.5. ``expires`` exists because the introductory rates
#: lapse on 31 Dec 2026 and the app must warn when they do (spec §21.6).
PRICING = {
    "expires": "2026-12-31",
    "currency": "USD",
    "per_1m_tokens": {
        "gemini-3.7-flash": {"input": 0.75, "output": 3.75,
                             "batch_input": 0.375, "batch_output": 1.875},
        "gemini-3.6-flash": {"input": 0.75, "output": 3.75,
                             "batch_input": 0.375, "batch_output": 1.875},
        "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50,
                                  "batch_input": 0.15, "batch_output": 1.25},
        "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50,
                                  "batch_input": 0.125, "batch_output": 0.75},
    },
}

#: Spec §7.2 — editable from the Settings screen.
SIMILARITY = {"auto_merge": 0.92, "merge_queue": 0.82}

DEFAULT_SETTINGS: dict[str, object] = {
    "pricing": PRICING,
    "similarity_thresholds": SIMILARITY,
    "autosave_debounce_ms": 800,
    "autosave_interval_ms": 30000,
    "session_defaults": {"practice_count": 20, "revision_count": 10},
    "interview_mode": False,
    "fx_rate_usd_to_gbp": None,
    "monthly_cap_usd": None,
    "sidebar_left_collapsed": False,
    "sidebar_right_collapsed": False,
    "schema_phase": 1,
}

#: A calm starting point, not a curriculum. The user renames or deletes these.
SEED_TREE: list[tuple[str, str, list[tuple[str, list[str]]]]] = [
    ("GenAI", "#6366F1", [
        ("Retrieval", ["Hybrid search", "Chunking strategies"]),
        ("Evaluation", ["LLM-as-judge"]),
    ]),
    ("Systems", "#0EA5E9", [
        ("Databases", ["Indexing", "Transactions"]),
    ]),
    ("Mathematics", "#F59E0B", [
        ("Linear algebra", ["Eigendecomposition"]),
    ]),
]


def seed_settings(session: Session) -> int:
    """Insert any missing default settings. Never overwrites a user's value."""
    now = datetime.now(timezone.utc)
    written = 0
    for key, value in DEFAULT_SETTINGS.items():
        if session.get(Setting, key) is None:
            session.add(Setting(key=key, value_json=json.dumps(value),
                                updated_at=now))
            written += 1
    return written


def seed_subjects(session: Session) -> int:
    """Seed the starter tree, but only into a database with no subjects."""
    if os.environ.get("RNL_SEED_SUBJECTS", "1") == "0":
        return 0
    existing = session.exec(select(Subject).limit(1)).first()
    if existing is not None:
        return 0

    created = 0
    for s_order, (subject_name, colour, topics) in enumerate(SEED_TREE):
        subject = Subject(name=subject_name, colour=colour, sort_order=s_order)
        session.add(subject)
        session.flush()
        created += 1
        for t_order, (topic_name, subtopics) in enumerate(topics):
            topic = Topic(subject_id=subject.id, name=topic_name,
                          sort_order=t_order)
            session.add(topic)
            session.flush()
            created += 1
            for st_order, subtopic_name in enumerate(subtopics):
                session.add(Subtopic(topic_id=topic.id, name=subtopic_name,
                                     sort_order=st_order))
                created += 1
    return created


def seed_all(session: Session) -> dict[str, int]:
    counts = {
        "settings": seed_settings(session),
        "hierarchy": seed_subjects(session),
    }
    if any(counts.values()):
        log.info("Seeded %s settings, %s hierarchy rows",
                 counts["settings"], counts["hierarchy"])
    return counts
