"""A deterministic provider for tests (spec §19).

"One end-to-end smoke test: seed a note → run pipeline against a mocked
provider → assert concepts, review items, and MCQs exist."

This never touches the network and never spends money. It is selected by
setting ``RNL_LLM_PROVIDER=mock``, which the test-suite does; the application
never selects it.
"""

from __future__ import annotations

import json
import os
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
        # A real call takes seconds; this one takes microseconds, which makes
        # "a job is still in flight" impossible to observe from outside.
        # RNL_MOCK_LATENCY_MS buys a test that window without a sleep in the
        # pipeline itself.
        try:
            self.latency_s = max(0.0, float(os.environ.get("RNL_MOCK_LATENCY_MS", "0")) / 1000)
        except ValueError:
            self.latency_s = 0.0

    def _next(self, user_input: str, schema: type[BaseModel]) -> Any:
        if self.responses:
            return self.responses.pop(0)
        if self.builder is not None:
            return self.builder(user_input, schema)
        if schema.__name__ == "MCQBatch":
            return default_mcqs(user_input)
        if schema.__name__ == "GeneratedQuestion":
            return default_question(user_input)
        if schema.__name__ == "EvaluationResult":
            return default_evaluation(user_input)
        return default_extraction(user_input)

    def generate_text(self, *, system_instruction: str, user_input: str,
                      model: str, thinking_level: str | None = None,
                      prompt_version: str = "") -> LLMResult:
        self.calls.append({"kind": "text", "model": model,
                           "input": user_input,
                           "thinking_level": thinking_level})
        if self.latency_s:
            time.sleep(self.latency_s)
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
        if self.latency_s:
            time.sleep(self.latency_s)
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


_CONCEPT = re.compile(r"CONCEPT:\s*(.+)")
_COUNT = re.compile(r"COUNT:\s*(\d+)")


def default_mcqs(user_input: str) -> dict:
    """Ten coherent MCQs for the requested concept (spec §9.1, §11.2).

    Stems are numbered so they are distinct, which matters: the generator
    de-duplicates by stem, and identical stems would silently collapse a pool
    of ten into a pool of one.
    """
    concept_match = _CONCEPT.search(user_input)
    concept = concept_match.group(1).strip() if concept_match else "the concept"
    count_match = _COUNT.search(user_input)
    count = int(count_match.group(1)) if count_match else 10

    questions = []
    for index in range(count):
        questions.append({
            "stem": f"Q{index + 1}: which statement about {concept} holds?",
            "options": [
                {"id": "a", "text": f"The correct account of {concept}"},
                {"id": "b", "text": "A plausible but subtly wrong condition"},
                {"id": "c", "text": "An adjacent concept mistaken for this one"},
                {"id": "d", "text": "A common confusion about the boundary case"},
            ],
            "correct_option_id": "a",
            "explanation": f"Option a states {concept} accurately.",
            "distractor_rationales": {
                "b": "The condition is reversed.",
                "c": "That describes a neighbouring idea.",
                "d": "True only outside the stated boundary.",
            },
            "dimension": "recall" if index % 3 else "explain",
            "difficulty": 3,
        })
    return {"questions": questions}


_DIMENSION = re.compile(r"DIMENSION:\s*(\w+)")
_KEY_POINTS = re.compile(r"KEY_POINTS:\n((?:- .*\n?)+)")


def default_question(user_input: str) -> dict:
    """One prose question with 3-6 independently checkable key points."""
    concept_match = _CONCEPT.search(user_input)
    concept = concept_match.group(1).strip() if concept_match else "the concept"
    dimension_match = _DIMENSION.search(user_input)
    dimension = dimension_match.group(1) if dimension_match else "explain"
    rephrase = "REPHRASE" in user_input

    lead = "In a different setting, walk through" if rephrase else "Walk through"
    return {
        "question_text": f"{lead} how {concept} behaves, and why ({dimension}).",
        "expected_answer": f"A correct account of {concept}.",
        "key_points": [
            f"States what {concept} is",
            f"Explains why {concept} matters",
            f"Names a condition under which {concept} fails",
        ],
        "common_misconceptions": [f"Confusing {concept} with a neighbouring idea"],
        "difficulty": 3,
    }


def default_evaluation(user_input: str) -> dict:
    """Judge the answer by a deterministic rule the tests can steer.

    The learner's answer is scanned for each key point's leading words. This is
    crude on purpose: it makes the *rating derivation* testable without making
    the test depend on a model's judgement.
    """
    block = _KEY_POINTS.search(user_input)
    points = []
    if block:
        points = [line[2:].strip() for line in block.group(1).splitlines()
                  if line.startswith("- ")]

    answer = user_input.split("LEARNER_ANSWER:", 1)[-1].strip().lower()
    hits = []
    for point in points:
        probe = " ".join(point.split()[:3]).lower()
        hits.append({"point": point, "hit": probe in answer})

    return {
        "key_point_hits": hits,
        "factually_incorrect_claims": (
            ["An incorrect claim"] if "wrongclaim" in answer else []
        ),
        "misconceptions": (
            ["A revealed misconception"] if "misconception" in answer else []
        ),
        "feedback": "This covered some ground; the missing piece is the "
                    "failure condition.",
        "suggested_rating": "good",
    }
