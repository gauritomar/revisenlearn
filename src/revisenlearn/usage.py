"""Cost and token accounting for the Usage screen (spec §12.6 **[LOCKED]**).

"Gemini's API does not expose account spend." Everything here is derived from
the `usageMetadata` token counts written to `llm_runs` at call time, which is
why the screen must be labelled **"Estimated — from token counts, not billing
data"**.

**Soft cap only.** At 80% of the monthly cap, show a banner. At 100%, show a
stronger banner and require one confirmation click before each further LLM
call. "Never hard-block — being unable to study because of a budget setting is
worse than the overspend."
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from .models import Concept, LLMRun, Setting, Subject, Topic

log = logging.getLogger(__name__)

FX_KEY = "fx_rate_usd_to_gbp"
CAP_KEY = "monthly_cap_usd"

WARN_AT = 0.80
CAP_AT = 1.00

BILLING_CONSOLE_URL = "https://console.cloud.google.com/billing"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _setting(session: Session, key: str):
    row = session.get(Setting, key)
    if row is None:
        return None
    try:
        return json.loads(row.value_json)
    except json.JSONDecodeError:
        return None


def month_bounds(when: date) -> tuple[date, date]:
    first = when.replace(day=1)
    nxt = date(first.year + (first.month == 12), (first.month % 12) + 1, 1)
    return first, nxt


def _runs_in_month(session: Session, when: date) -> list[LLMRun]:
    first, nxt = month_bounds(when)
    rows = session.exec(select(LLMRun)).all()
    out = []
    for row in rows:
        created = _aware(row.created_at)
        if created is None:
            continue
        if first <= created.date() < nxt:
            out.append(row)
    return out


def _spend(runs: list[LLMRun]) -> tuple[float, int]:
    """Returns (total, unpriced_count). A run with no price on file is counted
    separately rather than silently treated as free."""
    total = sum(r.estimated_cost_usd or 0.0 for r in runs)
    unpriced = sum(1 for r in runs if r.estimated_cost_usd is None)
    return round(total, 6), unpriced


def cap_state(session: Session, when: date | None = None) -> dict:
    """Where this month's spend sits against the soft cap."""
    when = when or _now().date()
    runs = _runs_in_month(session, when)
    spent, unpriced = _spend(runs)
    cap = _setting(session, CAP_KEY)
    cap = float(cap) if cap else None

    ratio = (spent / cap) if cap else None
    if cap is None:
        level = "none"
    elif ratio >= CAP_AT:
        level = "over"
    elif ratio >= WARN_AT:
        level = "warn"
    else:
        level = "ok"

    return {
        "month": when.strftime("%Y-%m"),
        "spent_usd": spent,
        "cap_usd": cap,
        "ratio": round(ratio, 4) if ratio is not None else None,
        "level": level,
        # Spec §12.6 — at 100% require one confirmation before each further
        # call. Never a hard block.
        "requires_confirmation": level == "over",
        "unpriced_calls": unpriced,
    }


def summary(session: Session, when: date | None = None) -> dict:
    """Everything the Usage screen shows."""
    when = when or _now().date()
    runs = _runs_in_month(session, when)
    spent, unpriced = _spend(runs)

    fx = _setting(session, FX_KEY)
    fx = float(fx) if fx else None

    # Daily sparkline across the month so far.
    first, nxt = month_bounds(when)
    by_day: dict[str, float] = defaultdict(float)
    for row in runs:
        created = _aware(row.created_at)
        if created:
            by_day[created.date().isoformat()] += row.estimated_cost_usd or 0.0

    days: list[dict] = []
    cursor = first
    while cursor < nxt and cursor <= when:
        days.append({"date": cursor.isoformat(),
                     "usd": round(by_day.get(cursor.isoformat(), 0.0), 6)})
        cursor += timedelta(days=1)

    by_task: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0}
    )
    for row in runs:
        entry = by_task[row.task]
        entry["calls"] += 1
        entry["input_tokens"] += row.input_tokens
        entry["output_tokens"] += row.output_tokens
        entry["usd"] += row.estimated_cost_usd or 0.0

    return {
        "month": when.strftime("%Y-%m"),
        # Spec §12.6 — this label is not decoration.
        "disclaimer": "Estimated — from token counts, not billing data",
        "billing_console_url": BILLING_CONSOLE_URL,
        "spent_usd": spent,
        "spent_gbp": round(spent * fx, 4) if fx else None,
        "fx_rate": fx,
        "calls": len(runs),
        "input_tokens": sum(r.input_tokens for r in runs),
        "output_tokens": sum(r.output_tokens for r in runs),
        "cached_tokens": sum(r.cached_tokens for r in runs),
        "unpriced_calls": unpriced,
        "cap": cap_state(session, when),
        "daily": days,
        "by_task": [
            {"task": task, **{k: (round(v, 6) if isinstance(v, float) else v)
                              for k, v in entry.items()}}
            for task, entry in sorted(by_task.items(),
                                      key=lambda kv: -kv[1]["usd"])
        ],
    }


def by_concept(session: Session, limit: int = 100) -> list[dict]:
    """Spec §12.6 — "a per-concept table — 'Transformer attention · 47.2k
    tokens · ₹18.40 across 23 generations'".

    All time, not just this month: the question a per-concept table answers is
    "what has this concept cost me", not "what did it cost in August".
    """
    fx = _setting(session, FX_KEY)
    fx = float(fx) if fx else None

    rows: dict[int, dict] = {}
    for run in session.exec(
        select(LLMRun).where(LLMRun.concept_id.is_not(None))
    ).all():
        entry = rows.setdefault(run.concept_id, {
            "concept_id": run.concept_id, "concept_name": None,
            "generations": 0, "tokens": 0, "usd": 0.0,
        })
        entry["generations"] += 1
        entry["tokens"] += run.input_tokens + run.output_tokens
        entry["usd"] += run.estimated_cost_usd or 0.0

    for concept_id, entry in rows.items():
        concept = session.get(Concept, concept_id)
        entry["concept_name"] = (concept.canonical_name if concept
                                 else "(deleted)")
        entry["usd"] = round(entry["usd"], 6)
        entry["gbp"] = round(entry["usd"] * fx, 4) if fx else None

    return sorted(rows.values(), key=lambda e: -e["usd"])[:limit]


def by_hierarchy(session: Session) -> dict:
    """Spec §12.6 — "a breakdown by subject and topic"."""
    subjects = {s.id: s.name for s in session.exec(select(Subject)).all()}
    topics = {t.id: (t.name, t.subject_id)
              for t in session.exec(select(Topic)).all()}
    concepts = {c.id: c for c in session.exec(select(Concept)).all()}

    per_subject: dict[str, float] = defaultdict(float)
    per_topic: dict[tuple[str, str], float] = defaultdict(float)

    for run in session.exec(
        select(LLMRun).where(LLMRun.concept_id.is_not(None))
    ).all():
        concept = concepts.get(run.concept_id)
        if concept is None:
            continue
        cost = run.estimated_cost_usd or 0.0
        subject_name = subjects.get(concept.subject_id, "(unfiled)")
        per_subject[subject_name] += cost
        if concept.topic_id in topics:
            topic_name = topics[concept.topic_id][0]
            per_topic[(subject_name, topic_name)] += cost

    return {
        "by_subject": sorted(
            ({"subject": name, "usd": round(v, 6)}
             for name, v in per_subject.items()),
            key=lambda e: -e["usd"],
        ),
        "by_topic": sorted(
            ({"subject": s, "topic": t, "usd": round(v, 6)}
             for (s, t), v in per_topic.items()),
            key=lambda e: -e["usd"],
        ),
    }
