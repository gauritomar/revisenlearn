"""Gemini, on the Interactions API (spec §12 **[LOCKED]**).

§12.1: use `client.interactions.create` from `google-genai` v2.0.0+. The legacy
`generateContent` path is not used.

§12.3, critical: do **not** set `temperature`, `top_p`, `top_k` or
`candidate_count` for any Gemini 3.x model — Google deprecates them, and
lowering temperature causes looping on structured tasks. Use `thinking_level`,
never `thinking_budget`, and never both. Determinism comes from strict system
instructions and rigid JSON schemas.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Sequence

from pydantic import BaseModel, ValidationError

from ..embeddings import get_embedder
from .base import LLMError, LLMResult, SchemaValidationError, Usage

log = logging.getLogger(__name__)

#: §12.3. Setting any of these is a bug, so it is asserted rather than trusted.
FORBIDDEN_PARAMETERS = ("temperature", "top_p", "top_k", "candidate_count",
                        "thinking_budget")

VALID_THINKING_LEVELS = ("minimal", "low", "medium", "high")

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


class GeminiProvider:
    """The real provider. Constructing it does not make a network call."""

    name = "gemini"

    def __init__(self, api_key: str, *, client: Any = None) -> None:
        if not api_key and client is None:
            raise LLMError("No Gemini API key available")
        self._api_key = api_key
        self._client = client

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    # -- internals ---------------------------------------------------------

    def _create(self, *, system_instruction: str, user_input: str, model: str,
                thinking_level: str | None,
                response_format: dict | None) -> Any:
        if thinking_level is not None and thinking_level not in VALID_THINKING_LEVELS:
            raise LLMError(
                f"thinking_level must be one of {VALID_THINKING_LEVELS}, "
                f"got {thinking_level!r}"
            )

        body: dict[str, Any] = {
            "model": model,
            "system_instruction": system_instruction,
            "input": user_input,
        }
        if thinking_level is not None:
            # generation_config carries thinking_level; nothing else is set,
            # per §12.3.
            body["generation_config"] = {"thinking_level": thinking_level}
        if response_format is not None:
            body["response_format"] = response_format

        # Belt and braces: prove we never send a forbidden parameter.
        flat = {**body, **body.get("generation_config", {})}
        offenders = [p for p in FORBIDDEN_PARAMETERS if p in flat]
        if offenders:
            raise LLMError(
                f"Spec §12.3 forbids these parameters on Gemini 3.x: {offenders}"
            )

        try:
            return self._get_client().interactions.create(**body)
        except Exception as exc:  # normalise every SDK failure
            raise LLMError(f"Gemini call failed: {exc}") from exc

    @staticmethod
    def _usage_of(interaction: Any) -> Usage:
        usage = getattr(interaction, "usage", None)
        if usage is None:
            return Usage()
        return Usage(
            input_tokens=int(getattr(usage, "total_input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "total_output_tokens", 0) or 0),
            cached_tokens=int(getattr(usage, "total_cached_tokens", 0) or 0),
        )

    @staticmethod
    def _text_of(interaction: Any) -> str:
        text = getattr(interaction, "output_text", None)
        if text is None:
            raise LLMError("Gemini returned no output_text")
        return text if isinstance(text, str) else str(text)

    # -- protocol ----------------------------------------------------------

    def generate_text(self, *, system_instruction: str, user_input: str,
                      model: str, thinking_level: str | None = None,
                      prompt_version: str = "") -> LLMResult:
        started = time.monotonic()
        interaction = self._create(
            system_instruction=system_instruction, user_input=user_input,
            model=model, thinking_level=thinking_level, response_format=None,
        )
        return LLMResult(
            text=self._text_of(interaction),
            usage=self._usage_of(interaction),
            model=model,
            prompt_version=prompt_version,
            thinking_level=thinking_level,
            latency_ms=int((time.monotonic() - started) * 1000),
            raw=interaction,
        )

    def generate_structured(self, *, system_instruction: str, user_input: str,
                            model: str, schema: type[BaseModel],
                            thinking_level: str | None = None,
                            prompt_version: str = "") -> LLMResult:
        """Spec §11 — retry exactly once with the validation error appended,
        then fail with the raw response preserved."""
        started = time.monotonic()
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": schema.model_json_schema(),
            },
        }

        attempt_input = user_input
        last_error: str = ""
        raw_text = ""
        total = Usage()

        for attempt in (1, 2):
            interaction = self._create(
                system_instruction=system_instruction,
                user_input=attempt_input,
                model=model,
                thinking_level=thinking_level,
                response_format=response_format,
            )
            usage = self._usage_of(interaction)
            total = Usage(
                input_tokens=total.input_tokens + usage.input_tokens,
                output_tokens=total.output_tokens + usage.output_tokens,
                cached_tokens=total.cached_tokens + usage.cached_tokens,
            )
            raw_text = self._text_of(interaction)

            try:
                parsed = schema.model_validate_json(_strip_fences(raw_text))
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)
                if attempt == 1:
                    log.warning("Schema validation failed; retrying once")
                    attempt_input = (
                        f"{user_input}\n\n"
                        "Your previous response did not match the required "
                        "schema. Fix exactly these problems and return only "
                        f"valid JSON:\n{last_error}"
                    )
                    continue
                raise SchemaValidationError(
                    f"Response did not match {schema.__name__}: {last_error}",
                    raw_response=raw_text,
                ) from None

            return LLMResult(
                text=raw_text,
                usage=total,
                model=model,
                prompt_version=prompt_version,
                thinking_level=thinking_level,
                latency_ms=int((time.monotonic() - started) * 1000),
                parsed=parsed,
                raw=interaction,
            )

        raise SchemaValidationError(  # unreachable, kept for the type-checker
            f"Response did not match {schema.__name__}: {last_error}",
            raw_response=raw_text,
        )

    def embed(self, texts: Sequence[str]):
        """Embeddings are local (spec §2, §16) — never a Gemini call."""
        return get_embedder().embed(texts)


def _strip_fences(text: str) -> str:
    """Some models wrap JSON in a markdown fence despite a schema."""
    stripped = _FENCE.sub("", text).strip()
    return stripped or text


def json_dumps_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
