"""LLM provider selection.

Spec §12.2: swapping a model is a config change, never a code change. The
provider itself is chosen the same way — `config/providers.yaml` names it, and
`RNL_LLM_PROVIDER` overrides it so the test-suite can select the mock without
touching config.
"""

from __future__ import annotations

import logging
import os

from .. import config
from ..credentials import resolve_api_key
from .base import (
    LLMError,
    LLMProvider,
    LLMResult,
    SchemaValidationError,
    Usage,
)

log = logging.getLogger(__name__)

_override: LLMProvider | None = None


def set_provider(provider: LLMProvider | None) -> None:
    """Used by tests. The application never calls this."""
    global _override
    _override = provider


def get_provider() -> LLMProvider:
    if _override is not None:
        return _override

    name = os.environ.get("RNL_LLM_PROVIDER") or config.providers().get(
        "provider", "gemini"
    )

    if name == "mock":
        from .mock import MockProvider

        log.warning("Using the mock LLM provider — no real calls will be made")
        return MockProvider()

    if name == "gemini":
        from .gemini import GeminiProvider

        key, status = resolve_api_key()
        if not key:
            raise LLMError(
                "No Gemini API key. Add one to the macOS Keychain with: "
                "uv run python -m revisenlearn.credentials --import-to-keychain"
            )
        log.info("Gemini provider ready (key source: %s)", status.source)
        return GeminiProvider(api_key=key)

    raise LLMError(f"Unknown LLM provider {name!r}")


def task_config(task: str) -> dict:
    """Model, thinking_level and mode for a task, from providers.yaml (§12.2)."""
    tasks = config.providers().get("tasks", {})
    entry = tasks.get(task)
    if entry is None:
        raise LLMError(f"No provider config for task {task!r}")
    return entry


__all__ = [
    "LLMError",
    "LLMProvider",
    "LLMResult",
    "SchemaValidationError",
    "Usage",
    "get_provider",
    "set_provider",
    "task_config",
]
