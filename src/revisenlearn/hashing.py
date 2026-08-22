"""Content hashing for note blocks (spec §4.2).

``content_hash`` is the SHA-256 of the *normalised* block text so that
whitespace-only edits do not mark a processed block stale.
"""

from __future__ import annotations

import hashlib
import re

_WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    return _WS.sub(" ", (text or "").strip())


def content_hash(text: str) -> str:
    return hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()
