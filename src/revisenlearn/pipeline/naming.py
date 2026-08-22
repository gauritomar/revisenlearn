"""Job names (spec §8.1).

"`{adjective}-{animal}` from a built-in wordlist … plus a human date:
`amber-lynx · 22 Aug, 3:40 pm`. Names need not be globally unique; append a
numeric suffix on collision."
"""

from __future__ import annotations

import random
from datetime import datetime

from sqlmodel import Session, select

from ..models import PipelineJob

ADJECTIVES = (
    "amber", "quiet", "brisk", "candid", "dapper", "eager", "fleet", "gentle",
    "hazel", "ivory", "jaunty", "keen", "lucid", "mellow", "nimble", "opal",
    "placid", "quartz", "rapid", "slate", "tidy", "umber", "vivid", "warm",
)
ANIMALS = (
    "lynx", "heron", "otter", "marten", "falcon", "badger", "ibex", "kestrel",
    "raven", "seal", "tapir", "vole", "wren", "adder", "bison", "crane",
    "dormouse", "egret", "ferret", "gannet", "hare", "jackdaw",
)


def human_date(when: datetime) -> str:
    """`22 Aug, 3:40 pm` — no leading zeros, lowercase meridiem."""
    hour = when.hour % 12 or 12
    meridiem = "am" if when.hour < 12 else "pm"
    return f"{when.day} {when:%b}, {hour}:{when:%M} {meridiem}"


def generate_name(session: Session, when: datetime,
                  rng: random.Random | None = None) -> str:
    """`{adjective}-{animal} · {date}`, with a numeric suffix on collision."""
    rng = rng or random.Random()
    base = f"{rng.choice(ADJECTIVES)}-{rng.choice(ANIMALS)}"
    stamped = f"{base} · {human_date(when)}"

    existing = {
        row.name
        for row in session.exec(
            select(PipelineJob).where(PipelineJob.name.startswith(base))
        ).all()
    }
    if stamped not in existing:
        return stamped

    suffix = 2
    while f"{base}-{suffix} · {human_date(when)}" in existing:
        suffix += 1
    return f"{base}-{suffix} · {human_date(when)}"
