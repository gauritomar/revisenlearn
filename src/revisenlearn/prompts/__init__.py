"""Versioned prompt files (spec §11 **[LOCKED]**).

"All prompts live in `backend/prompts/` as versioned files … Never edit a
prompt in place — create `_v2` and switch the config."

This package is that directory; the repo has no `backend/` tree, so the prompts
sit inside the Python package where they ship with it. `prompt_version` is
written to `llm_runs` and to every generated artefact.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


class PromptNotFound(LookupError):
    pass


@lru_cache(maxsize=None)
def load_prompt(version: str) -> str:
    """``load_prompt("concept_extraction_v1")`` -> the file's text."""
    path = PROMPT_DIR / f"{version}.md"
    if not path.exists():
        raise PromptNotFound(f"No prompt file for version {version!r}")
    return path.read_text(encoding="utf-8").strip()


def available() -> list[str]:
    return sorted(p.stem for p in PROMPT_DIR.glob("*.md"))
