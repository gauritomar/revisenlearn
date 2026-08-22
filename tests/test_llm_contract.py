"""What we actually send to Gemini (spec §12 **[LOCKED]**).

The first real "Process notes" failed with

    Error code: 400 … The value 'json_schema' is not supported for 'type' at
    'response_format'. Supported values: … 'object' …

because the provider was sending OpenAI's envelope. Nothing in the suite
checked the shape of the request, so nothing caught it: the mock provider
never sees a `response_format` at all. These tests are that check, and they
cost nothing to run.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, Field

from revisenlearn.llm.base import ProviderRefusedError
from revisenlearn.llm.gemini import (
    FORBIDDEN_PARAMETERS,
    GeminiProvider,
    _classify,
    json_schema_for,
)
from revisenlearn.pipeline.schemas import ExtractionResult


class Nested(BaseModel):
    flag: bool = True


class Outer(BaseModel):
    """A model that contains another one, which is what Pydantic lifts into
    definitions and points at by reference."""

    name: str = Field(min_length=1)
    inner: Nested
    items: list[Nested] = []


class _Recorder:
    """Stands in for the SDK client and remembers the request body."""

    def __init__(self, output: str = '{"answer": "blue"}') -> None:
        self.bodies: list[dict] = []
        self.interactions = self
        self._output = output

    def create(self, **body):
        self.bodies.append(body)
        return type("Interaction", (), {"output_text": self._output, "usage": None})()


def test_the_response_format_is_the_schema_not_an_envelope() -> None:
    """The 400 said which values `type` may take; `json_schema` is not one."""
    fmt = json_schema_for(ExtractionResult)

    assert fmt["type"] == "object"
    assert "json_schema" not in fmt
    assert set(fmt) <= {"type", "properties", "required", "description", "items"}


def test_refs_are_inlined_because_the_api_does_not_resolve_them() -> None:
    fmt = json_schema_for(Outer)

    def keys(node):
        """Every key in the tree — checked structurally, because a model's
        own description could mention these words in prose."""
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from keys(item)

    assert "$ref" not in set(keys(fmt))
    assert "$defs" not in set(keys(fmt))
    # The nested model survived, inlined in both places it appears.
    assert fmt["properties"]["inner"]["properties"]["flag"]["type"] == "boolean"
    assert fmt["properties"]["items"]["items"]["properties"]["flag"]["type"] == "boolean"


def test_keywords_the_api_rejects_are_stripped() -> None:
    text = json.dumps(json_schema_for(Outer))
    for keyword in ("title", "default", "additionalProperties"):
        assert f'"{keyword}"' not in text


def test_a_structured_call_sends_what_we_think_it_does() -> None:
    """§12.3 [LOCKED] — no temperature, top_p, top_k, candidate_count or
    thinking_budget, ever."""
    class Tiny(BaseModel):
        answer: str

    recorder = _Recorder()
    provider = GeminiProvider("unused", client=recorder)
    provider.generate_structured(
        system_instruction="sys", user_input="hi", model="gemini-3-flash-preview",
        schema=Tiny, thinking_level="low", prompt_version="v1",
    )

    body = recorder.bodies[0]
    assert body["model"] == "gemini-3-flash-preview"
    assert body["response_format"]["type"] == "object"
    assert body["generation_config"] == {"thinking_level": "low"}
    flat = {**body, **body.get("generation_config", {})}
    for forbidden in FORBIDDEN_PARAMETERS:
        assert forbidden not in flat


@pytest.mark.parametrize("message, reason, retryable", [
    ("Error code: 429 - {'error': {'message': 'Your prepayment credits are "
     "depleted. Please go to AI Studio'}}", "credits", False),
    ("Error code: 400 - {'error': {'message': \"The value 'json_schema' is not "
     "supported\", 'code': 'invalid_request'}}", "request", False),
    ("Error code: 403 - API key not valid", "auth", False),
])
def test_provider_failures_say_what_to_do(message, reason, retryable) -> None:
    """A Retry button pointed at a depleted account spends again on the same
    wall, so the reason has to survive the round trip."""
    error = _classify(Exception(message))

    assert isinstance(error, ProviderRefusedError)
    assert error.reason == reason
    assert error.retryable is retryable
    assert error.action
