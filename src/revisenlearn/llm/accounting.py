"""LLM accounting (spec §1.6 **[LOCKED]**).

"Every LLM output is logged with its prompt version, model, and token counts.
No exceptions."

Cost is priced from the `settings.pricing` table seeded in §12.5, so the
introductory rates expiring on 31 Dec 2026 can be updated without a code
change (§21.6).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlmodel import Session

from .base import LLMResult
from ..models import LLMRun, Setting

log = logging.getLogger(__name__)

PRICING_KEY = "pricing"


@dataclass(frozen=True)
class Pricing:
    per_1m: dict
    expires: date | None

    def rate(self, model: str, kind: str, batch: bool) -> float | None:
        entry = self.per_1m.get(model)
        if entry is None:
            return None
        key = f"batch_{kind}" if batch else kind
        value = entry.get(key)
        return float(value) if value is not None else None

    def is_expired(self, on: date | None = None) -> bool:
        if self.expires is None:
            return False
        return (on or date.today()) > self.expires


def load_pricing(session: Session) -> Pricing:
    row = session.get(Setting, PRICING_KEY)
    if row is None:
        return Pricing(per_1m={}, expires=None)
    try:
        value = json.loads(row.value_json)
    except json.JSONDecodeError:
        log.warning("Unreadable pricing setting")
        return Pricing(per_1m={}, expires=None)

    expires = None
    raw_expires = value.get("expires")
    if raw_expires:
        try:
            expires = date.fromisoformat(raw_expires)
        except ValueError:
            expires = None
    return Pricing(per_1m=value.get("per_1m_tokens", {}), expires=expires)


def estimate_cost_usd(pricing: Pricing, model: str, input_tokens: int,
                      output_tokens: int, cached_tokens: int = 0,
                      batch: bool = False) -> float | None:
    """Returns None for a model with no price on file, rather than 0.0 — a
    missing price is not a free call, and the Usage screen should say so."""
    in_rate = pricing.rate(model, "input", batch)
    out_rate = pricing.rate(model, "output", batch)
    if in_rate is None or out_rate is None:
        return None

    # Cached input tokens are billed at the input rate here; §12.4's caching
    # discount is applied by the provider, and `cached_tokens` is reported
    # separately so the saving is visible rather than assumed.
    billable_input = max(0, input_tokens - cached_tokens)
    cost = (billable_input / 1_000_000) * in_rate
    cost += (cached_tokens / 1_000_000) * in_rate
    cost += (output_tokens / 1_000_000) * out_rate
    return round(cost, 8)


def record_run(
    session: Session,
    *,
    task: str,
    result: LLMResult | None = None,
    provider: str = "gemini",
    model: str | None = None,
    prompt_version: str | None = None,
    job_id: int | None = None,
    session_id: int | None = None,
    concept_id: int | None = None,
    success: bool = True,
    error_text: str | None = None,
) -> LLMRun:
    """Write one `llm_runs` row. Called for failures too — §1.6 says no
    exceptions, and a failed call still costs tokens."""
    pricing = load_pricing(session)
    usage = result.usage if result is not None else None
    resolved_model = model or (result.model if result else "unknown")
    request_mode = result.request_mode if result else "standard"

    cost = None
    if usage is not None:
        cost = estimate_cost_usd(
            pricing, resolved_model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_tokens=usage.cached_tokens,
            batch=(request_mode == "batch"),
        )

    row = LLMRun(
        job_id=job_id,
        session_id=session_id,
        task=task,
        provider=provider,
        model=resolved_model,
        prompt_version=prompt_version or (result.prompt_version if result else None),
        thinking_level=result.thinking_level if result else None,
        request_mode=request_mode,
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
        cached_tokens=usage.cached_tokens if usage else 0,
        latency_ms=result.latency_ms if result else None,
        estimated_cost_usd=cost,
        success=success,
        error_text=error_text,
        concept_id=concept_id,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.flush()
    return row
