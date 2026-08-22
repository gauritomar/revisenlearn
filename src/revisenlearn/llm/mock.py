"""A deterministic provider for tests (spec §19).

"One end-to-end smoke test: seed a note → run pipeline against a mocked
provider → assert concepts, review items, and MCQs exist."

This never touches the network and never spends money. It is selected by
setting ``RNL_LLM_PROVIDER=mock``, which the test-suite does; the application
never selects it.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Sequence

from pydantic import BaseModel

from ..embeddings import get_embedder
from .base import LLMResult, SchemaValidationError, Usage


class MockProvider:
    """Answers from a scripted queue, or from a plausible default."""

    name = "mock"

    def __init__(self, responses: list[Any] | None = None,
                 builder: Callable[[str, type[BaseModel]], Any] | None = None) -> None:
        self.responses = list(responses or [])
        self.builder = builder
        self.calls: list[dict] = []

    def _next(self, user_input: str, schema: type[BaseModel]) -> Any:
        if self.responses:
            return self.responses.pop(0)
        if self.builder is not None:
            return self.builder(user_input, schema)
        return default_extraction(user_input)

    def generate_text(self, *, system_instruction: str, user_input: str,
                      model: str, thinking_level: str | None = None,
                      prompt_version: str = "") -> LLMResult:
        self.calls.append({"kind": "text", "model": model,
                           "input": user_input,
                           "thinking_level": thinking_level})
        return LLMResult(
            text="mock", usage=_usage(user_input, "mock"), model=model,
            prompt_version=prompt_version, thinking_level=thinking_level,
            latency_ms=1,
        )

    def generate_structured(self, *, system_instruction: str, user_input: str,
                            model: str, schema: type[BaseModel],
                            thinking_level: str | None = None,
                            prompt_version: str = "") -> LLMResult:
        self.calls.append({"kind": "structured", "model": model,
                           "input": user_input, "schema": schema.__name__,
                           "thinking_level": thinking_level})
        started = time.monotonic()
        payload = self._next(user_input, schema)

        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, BaseModel):
            parsed, text = payload, payload.model_dump_json()
        else:
            text = payload if isinstance(payload, str) else json.dumps(payload)
            try:
                parsed = schema.model_validate_json(text)
            except Exception as exc:
                raise SchemaValidationError(str(exc), raw_response=text) from None

        return LLMResult(
            text=text, usage=_usage(user_input, text), model=model,
            prompt_version=prompt_version, thinking_level=thinking_level,
            latency_ms=max(1, int((time.monotonic() - started) * 1000)),
            parsed=parsed,
        )

    def embed(self, texts: Sequence[str]):
        return get_embedder().embed(texts)


def _usage(prompt: str, output: str) -> Usage:
    """Roughly four characters per token — enough for the accounting tests to
    exercise real arithmetic rather than zeros."""
    return Usage(input_tokens=max(1, len(prompt) // 4),
                 output_tokens=max(1, len(output) // 4),
                 cached_tokens=0)


_BLOCK_ID = re.compile(r"\[block (\d+)\]")


def default_extraction(user_input: str) -> dict:
    """Produce one plausible concept per heading-ish line in the chunk.

    Deliberately simple and deterministic: the pipeline's job is to be tested,
    not the model's.
    """
    block_ids = [int(m) for m in _BLOCK_ID.findall(user_input)]
    lines = [
        line.strip(" -*\t")
        for line in user_input.splitlines()
        if line.strip() and not line.strip().startswith(("SUBJECT", "TOPIC",
                                                         "SUBTOPIC", "LESSON",
                                                         "PATH"))
    ]
    lines = [_BLOCK_ID.sub("", line).strip() for line in lines]
    lines = [line for line in lines if len(line) > 8][:3]

    concepts = []
    for index, line in enumerate(lines):
        name = " ".join(line.split()[:4]).rstrip(".,;:")
        concepts.append({
            "name": name or f"Concept {index + 1}",
            "definition": line,
            "importance": 3,
            "difficulty": 3,
            "coverage_profile": {"recall": True, "explain": True,
                                 "apply": index == 0, "debug": False,
                                 "synthesis": False, "interview": True},
            "source_block_ids": block_ids or [],
        })

    edges = []
    if len(concepts) >= 2:
        edges.append({
            "source_name": concepts[0]["name"],
            "target_name": concepts[1]["name"],
            "relation_type": "related_to",
            "confidence": 0.7,
        })
    return {"concepts": concepts, "edges": edges}
