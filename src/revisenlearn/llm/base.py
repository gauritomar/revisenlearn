"""The LLM provider abstraction (spec §12.2 **[LOCKED]**).

"The provider abstraction (`LLMProvider` protocol with `generate_structured`,
`generate_text`, `embed`) must be respected — swapping a model is a config
change, never a code change."

Nothing above this layer imports `google.genai`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from pydantic import BaseModel


class LLMError(RuntimeError):
    """Any provider failure, normalised."""


class ProviderRefusedError(LLMError):
    """The provider refused the call for a reason retrying will not fix.

    Depleted credits, a rejected key, a bad request shape: all of these come
    back as an opaque HTTP error, and the pipeline used to surface them as
    "extraction failed" with a Retry button that spends again on the same
    wall. Carrying the reason lets the UI say what to actually do.
    """

    def __init__(self, message: str, *, reason: str, action: str) -> None:
        super().__init__(message)
        #: One of: credits | auth | request | rate_limit | provider.
        self.reason = reason
        #: What the user can do about it, in a sentence.
        self.action = action

    @property
    def retryable(self) -> bool:
        """Whether pressing Retry could plausibly work."""
        return self.reason in ("rate_limit", "provider")


class SchemaValidationError(LLMError):
    """The model returned JSON that does not match the requested schema.

    Spec §11: "All calls are wrapped so that a schema-validation failure
    retries once with the validation error appended, then fails the job with
    the raw response stored in `llm_runs.error_text`."
    """

    def __init__(self, message: str, raw_response: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response


@dataclass
class Usage:
    """Token counts, as reported by the provider."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class LLMResult:
    """One completed call, with everything §1.6 requires us to log."""

    text: str
    usage: Usage
    model: str
    prompt_version: str
    thinking_level: str | None = None
    request_mode: str = "standard"
    latency_ms: int = 0
    #: Populated by `generate_structured`.
    parsed: Any = None
    raw: Any = field(default=None, repr=False)


class LLMProvider(Protocol):
    """The whole surface. Adding a provider means implementing these three."""

    name: str

    def generate_text(
        self,
        *,
        system_instruction: str,
        user_input: str,
        model: str,
        thinking_level: str | None = None,
        prompt_version: str = "",
    ) -> LLMResult:
        ...

    def generate_structured(
        self,
        *,
        system_instruction: str,
        user_input: str,
        model: str,
        schema: type[BaseModel],
        thinking_level: str | None = None,
        prompt_version: str = "",
    ) -> LLMResult:
        """Return a result whose ``parsed`` is a validated ``schema`` instance.

        Implementations must retry exactly once on a validation failure, with
        the validation error appended to the input, then raise
        `SchemaValidationError` carrying the raw response.
        """
        ...

    def embed(self, texts: Sequence[str]) -> Any:
        ...
