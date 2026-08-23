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

### mcq_generation v2 — 2026-08-23
Model:     gemini-3.5-flash-lite   Thinking: low
Mode:      standard                Cached:   not yet
Changed:   Written as an interviewer rather than a quizmaster. A *new
           version*, not an edit to v1, per §11: never edit a prompt in
           place.
           - A named spread of question kinds — correctness, boundary,
             complexity, choice of approach, failure mode, trace,
             consequence — with a cap of three of any one, so a set cannot
             collapse into ten definition questions.
           - "Every stem must be answerable by thinking, not by remembering
             a phrase. If a question can be answered by matching wording to
             the notes, rewrite it."
           - Distractors must each encode one *nameable* mistake — an
             off-by-one, a reversed comparison, a rule applied outside its
             precondition — and the options must be mutually exclusive.
           - The request now carries the learner's own note text and the
             subject, not just the concept name and a one-line definition. A
             question generated from a definition is a question about a
             definition.
Because:   "Fix the question generator a little bit to be more algorithmically
           sound like ask me interview style questions."
Golden set: not yet run — §11.5's fixtures are still not written, so this
           change is checked by reading real output, not by a regression set.
           One live generation against real notes produced a failure-mode
           question ("if you always added, what would 'IV' give?"), the
           last-character boundary, and "why must you compare to the next
           character" — the kinds v1 did not reliably reach.

### question_generation v1 — 2026-08-22
Model:     gemini-3.7-flash        Thinking: low
Mode:      standard                Cached:   no
Changed:   First version. Transcribed verbatim from spec §11.3.
Because:   Phase 7.
Golden set: not yet run.

### question_generation v2_interview — 2026-08-22
Model:     gemini-3.7-flash        Thinking: low
Mode:      standard                Cached:   no
Changed:   Interview framing — "walk me through", trade-offs and
           justification rather than definitions. A *new version*, not an
           edit to v1, per §11: never edit a prompt in place. Selected
           automatically when the review item's dimension is `interview`.
Because:   Phase 10's "interview-specific prompt tuning".
Golden set: not yet run.

### evaluation v1 — 2026-08-22
Model:     gemini-3.7-flash        Thinking: low
Mode:      standard                Cached:   no
Changed:   First version. Transcribed verbatim from spec §11.4.
Because:   Phase 7.
Golden set: not yet run.

---

## Outstanding

**The golden set (§11.5) is not written.** `backend/evals/golden/` should hold
10 hand-checked note fixtures with expected concept counts and names, and 20
answer/key-point pairs with expected hit patterns, run against the live API
before any `prompt_version` change. Building it means spending real money on
real notes, so it is left for the user to seed with material they care about.
Until it exists, treat every prompt version bump as unverified.
