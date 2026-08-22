# Prompts

Prompt versions and their change history, per spec §20.

**Status: empty. No prompt exists yet.**

Prompts arrive in Phase 5 (`concept_extraction`, `edge_proposal`), Phase 6
(`mcq_generation`) and Phase 7 (`question_generation`, `evaluation`). Their
contracts are fixed by spec §11 `[LOCKED]` and must be implemented from there,
not invented here.

---

## Rules this file exists to enforce

From §1.6 and §11:

1. **Every LLM output is logged with its prompt version, model and token
   counts. No exceptions.** `llm_runs.prompt_version` is not nullable in
   practice — if a call cannot name its prompt version, it is a bug.
2. **A prompt change is a version bump**, recorded below with the date, what
   changed, and why.
3. **The golden set (§11.5) is run manually before any prompt version change.**
   A version bump with no golden-set run is not a release.
4. Determinism comes from strict system instructions and rigid JSON schemas —
   **never** from sampling parameters. §12.3 forbids setting `temperature`,
   `top_p`, `top_k` or `candidate_count` on any Gemini 3.x model, and forbids
   sending `thinking_budget` at all (use `thinking_level`). Sending both is an
   error, and lowering temperature causes looping on structured tasks.

## Format for each entry

    ### <task> v<N>  —  YYYY-MM-DD
    Model:     <model id>          Thinking: <minimal|low|medium|high>
    Mode:      <standard|batch>    Cached:   <yes|no>
    Changed:   <what moved>
    Because:   <what evidence prompted it>
    Golden set: <pass/fail counts, and which cases moved>

## Model assignments

Live in `config/providers.yaml`, per §12.2. Swapping a model is a config
change, never a code change — the `LLMProvider` protocol
(`generate_structured`, `generate_text`, `embed`) must be respected.

| Task | Model | Thinking | Mode |
|---|---|---|---|
| `concept_extraction` | `gemini-3.7-flash` | medium | standard |
| `mcq_generation` | `gemini-3.5-flash-lite` | low | **batch** |
| `question_generation` | `gemini-3.7-flash` | low | standard |
| `evaluation` | `gemini-3.7-flash` | low | standard |
| `edge_proposal` | `gemini-3.5-flash-lite` | low | standard |

---

## History

### concept_extraction v1 — 2026-08-22
Model:     gemini-3.7-flash        Thinking: medium
Mode:      standard                Cached:   not yet
Changed:   First version. Transcribed verbatim from spec §11.1.
Because:   Phase 5.
Golden set: not yet run — §11.5's fixtures are not written.

### mcq_generation v1 — 2026-08-22
Model:     gemini-3.5-flash-lite   Thinking: low
Mode:      standard (see note)     Cached:   not yet
Changed:   First version. Transcribed verbatim from spec §11.2.
Because:   Phase 6.
Golden set: not yet run.

**Note on mode.** §12.2 assigns MCQ generation to the Batch API for the 50%
discount. The current implementation issues standard interactive calls and
records `request_mode='standard'`, so the recorded cost is truthful rather
than claiming a discount that was not taken. Real batch submission is
outstanding — see DECISIONS.md §8.
