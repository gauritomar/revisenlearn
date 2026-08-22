# Revise & Learn — v1 Build Specification

**Package name:** `revisenlearn`
**Display name:** Revise & Learn
**Audience for this document:** Claude Code, building the application end-to-end.
**Deployment:** single user, single machine (MacBook M4, macOS), local-first, no cloud, no auth, no Docker.

---

## 0. How to read this document

This spec supersedes the earlier draft. Where it conflicts with any prior spec, **this document wins.**

Sections marked **[LOCKED]** are decided and must not be redesigned. Sections marked **[JUDGEMENT]** leave implementation latitude — pick something sensible and note the choice in `DECISIONS.md`.

Build in the phase order given in §18. Do not skip ahead to the knowledge graph.

---

## 1. Core principles **[LOCKED]**

1. **The concept is the durable learning object.** Notes are input. Questions are disposable probes. Concepts, review items, and the review log are what persist and accumulate value.
2. **Note-taking never blocks on anything.** No network call, no LLM, no pipeline stage sits between the user typing and the text being saved.
3. **Nothing is automatic.** The user presses a button to process notes. The system never silently spends money or mutates the graph in the background.
4. **Two review loops, deliberately separate.** MCQs are for volume and warm-up. Prose answers are for actual mastery. They do not share scoring machinery.
5. **Prose review is the point of the app.** Design decisions that make prose review feel lower-stakes and more approachable beat decisions that maximise throughput. See §9.6.
6. **Every LLM output is logged with its prompt version, model, and token counts.** No exceptions.
7. **Nothing is ever hard-deleted.** Soft-delete everywhere (`deleted_at` nullable timestamp). The SQLite file is the user's permanent record.

---

## 2. Stack **[LOCKED]**

**Backend**
- Python 3.12+, managed with `uv`
- FastAPI + Pydantic v2
- SQLModel (SQLAlchemy 2.x underneath) + Alembic migrations
- SQLite in WAL mode + FTS5 for full-text search
- `py-fsrs` for scheduling — do not reimplement FSRS
- `fastembed` for local embeddings, model `BAAI/bge-small-en-v1.5` (ONNX, ~130MB, ~300MB RAM, no PyTorch dependency)
- `google-genai` SDK v2.0.0+ for Gemini
- `pywebview` for the desktop window

**Frontend**
- React 18 + TypeScript + Vite
- Tiptap for the editor
- Zustand for UI state
- TanStack Query for server state
- Cytoscape.js for the graph (better than React Flow for large auto-laid-out graphs)
- Tailwind CSS
- **Light mode only.** No dark mode, no theme toggle, no `prefers-color-scheme` handling.

**Explicitly not used:** Docker, Redis, Celery, Postgres, any vector database, any auth system, sentence-transformers.

---

## 3. Naming taxonomy **[LOCKED]**

Use these exact terms in code, database, and UI. Three fixed levels — no arbitrary nesting.

```
Subject       GenAI                    (top level, ~5–10 total)
  Topic         Retrieval              (major area within a subject)
    Subtopic      Hybrid search        (optional; may be null)
      Note          "Hybrid search"    (the writing surface)
```

Cross-cutting labels use **Tags**, which attach to notes, resources, and concepts (`#interview`, `#leetcode`, `#revisit`). Tags are flat, user-created, and never hierarchical.

Other objects:

| Term | Meaning |
|---|---|
| **Resource** | Something to study: video, article, paper, problem set, course. Also the to-do item. |
| **Note** | A dated writing surface. Belongs to a Subtopic (or Topic if no Subtopic). Optionally linked to a Resource. |
| **Note Block** | One paragraph / bullet / heading within a Note. The unit of content hashing. |
| **Concept** | An extracted, chunky learnable idea. The durable object. |
| **Dimension** | One of: `recall`, `explain`, `apply`, `debug`, `synthesis`, `interview`. |
| **Review Item** | A (Concept × Dimension) pair. Owns one FSRS state. |
| **Question** | A generated prose probe. Ephemeral. |
| **MCQ** | A static multiple-choice question with stored options and answer. |
| **Pipeline Job** | One button-press processing run. Has a funky name. |
| **Practice Session** | An MCQ session. |
| **Revision Session** | A prose session. |

---

## 4. Notes and the writing surface **[LOCKED]**

### 4.1 Note structure

One note per (Subtopic, day) by default, but the user can create additional notes and rename them. Notes are **long and continuous** — the user writes mostly bullet points at an advanced level.

Editor blocks supported: paragraph, H1/H2/H3, bullet list, numbered list, quote, code block, divider, link. Nothing else. Bullets are the primary mode — make them fast and frictionless.

Autosave: debounced 800ms after typing stops, plus on blur, plus every 30s while active. Save writes the full block list for the note. Never show a "saving…" spinner that moves layout; use a small static status dot.

### 4.2 Processed-state indicator **[LOCKED]**

Every `note_block` carries a `content_hash` (SHA-256 of normalised text) and a nullable `processed_hash`.

- `processed_hash == content_hash` → block has been through the pipeline as it currently reads.
  Render with a **pale blue left border (2px, `#DBEAFE`)** and a small **`#` superscript** before the first character.
- `processed_hash IS NULL` → never processed. Render plain.
- `processed_hash != content_hash` → processed, then edited. Render with an **amber left border** and a `#` superscript with a tilde: `#~`. This is the "stale" state and it matters — the concepts derived from this block no longer reflect what it says.

A small counter in the note header: `12 processed · 4 new · 2 edited`.

### 4.3 Snapshot semantics **[LOCKED]**

When the user presses **Process notes**, the backend immediately copies the current text and hash of every unprocessed or stale block into `pipeline_job_blocks`. That copy is what the job works on. Anything typed after the button press is untouched by that job and stays visually unprocessed. This is non-negotiable — the user must be able to keep writing during a run and trust the indicators.

---

## 5. Resources and the to-do flow **[LOCKED]**

A Resource is both a study to-do and the anchor for notes.

**Fields:** `id`, `title`, `url`, `resource_type`, `description`, `status`, `priority`, `subject_id`, `topic_id`, `subtopic_id`, `progress_pct`, `progress_note`, `created_at`, `last_opened_at`, `completed_at`, `deleted_at`.

**Types:** `youtube_video`, `youtube_playlist`, `article`, `paper`, `pdf`, `book`, `course`, `problem_set`, `other`.

**Statuses:** `inbox` → `next` → `in_progress` → `completed` → `archived`.

**Progress** is an integer 0–100 that the user sets manually with a slider, plus a free-text `progress_note` ("stopped at chapter 4", "did problems 1–15"). Do not try to compute it.

### 5.1 The critical interaction

Adding a resource must take under five seconds: a single input where the user pastes a URL or types a title, with subject/topic pickers that default to the last-used values. If a URL is pasted, attempt to fetch the page `<title>` for the title field — one HTTP request, 3s timeout, fail silently to the raw URL.

Clicking a resource opens a split view:
- left: resource metadata, status control, progress slider, "Open link" button (opens in the default browser)
- right: the note for that resource + today's date, created on the spot if it doesn't exist

This is the primary daily entry point. Make it fast.

---

## 6. Data model **[LOCKED]**

SQLite, WAL mode, `busy_timeout=5000`, `foreign_keys=ON`. All tables have `created_at`; most have `updated_at` and `deleted_at`.

```sql
-- Hierarchy
subjects(id, name, colour, sort_order, created_at, deleted_at)
topics(id, subject_id, name, sort_order, created_at, deleted_at)
subtopics(id, topic_id, name, sort_order, created_at, deleted_at)
tags(id, name, colour, created_at)
taggings(id, tag_id, target_type, target_id)      -- target_type: note|resource|concept

-- Notes
notes(id, title, study_date, subject_id, topic_id, subtopic_id, resource_id,
      created_at, updated_at, deleted_at)
note_blocks(id, note_id, position, block_type, text, content_hash,
            processed_hash, created_at, updated_at, deleted_at)

-- Resources
resources(id, title, url, resource_type, description, status, priority,
          subject_id, topic_id, subtopic_id, progress_pct, progress_note,
          created_at, last_opened_at, completed_at, deleted_at)

-- Concepts and identity
concepts(id, canonical_name, normalised_name, definition, subject_id, topic_id,
         subtopic_id, importance, difficulty, status, coverage_profile_json,
         created_by_job_id, created_at, updated_at, deleted_at)
         -- status: active | stale | archived
concept_aliases(id, concept_id, alias, normalised_alias, source, created_at)
         -- source: extraction | merge | manual
concept_merges(id, merged_from_id, merged_into_id, similarity, decided_by,
               job_id, created_at, reverted_at)
         -- decided_by: auto | user
concept_sources(id, concept_id, note_block_id, note_id, job_id, created_at,
                invalidated_at)
concept_edges(id, source_concept_id, target_concept_id, relation_type,
              confidence, created_by, status, job_id, created_at, deleted_at)
         -- relation_type: prerequisite_of | related_to | part_of |
         --                contrasts_with | depends_on | causes
         -- created_by: llm | user
         -- status: proposed | accepted | rejected
embeddings(id, target_type, target_id, vector BLOB, model, dim, created_at)
         -- target_type: concept | note_block

-- MCQs (static, eager)
mcqs(id, concept_id, dimension, stem, options_json, correct_option_id,
     explanation, distractor_rationale_json, difficulty, status,
     times_served, times_correct, consecutive_correct, last_served_at,
     prompt_version, model, job_id, created_at, retired_at, deleted_at)
     -- status: active | retired
mcq_attempts(id, mcq_id, concept_id, session_id, selected_option_id,
             is_correct, response_ms, created_at)

-- Prose questions (dynamic, lazy)
questions(id, concept_id, review_item_id, dimension, question_text,
          expected_answer, key_points_json, common_misconceptions_json,
          difficulty, source_note_ids_json, generation_reason,
          prompt_version, model, embedding_id, created_at, deleted_at)
          -- generation_reason: due | retest_same | retest_rephrased | manual
question_attempts(id, question_id, review_item_id, session_id, user_answer,
                  is_retest, retest_of_attempt_id, evaluator_json,
                  evaluator_rating, user_override_rating, final_rating,
                  response_ms, created_at)

-- Scheduling
review_items(id, concept_id, dimension, fsrs_stability, fsrs_difficulty,
             fsrs_state, fsrs_step, due_at, last_reviewed_at, lapses, reps,
             suspended, created_at, updated_at)
review_logs(id, review_item_id, concept_id, dimension, question_id,
            question_attempt_id, rating, evaluator_rating,
            user_override_rating, evaluator_json, response_ms,
            due_before, due_after, stability_before, stability_after,
            difficulty_before, difficulty_after, is_retest, created_at)
            -- APPEND ONLY. No UPDATE, no DELETE, ever.
misconceptions(id, concept_id, text, first_seen_at, last_seen_at,
               times_seen, resolved_at)

-- Sessions
sessions(id, session_type, scope_json, planned_count, completed_count,
         correct_count, started_at, finished_at, duration_ms)
         -- session_type: practice | revision
session_items(id, session_id, position, item_type, mcq_id, question_id,
              review_item_id, selection_bucket, served_at, answered_at)
              -- item_type: mcq | question
              -- selection_bucket: new | failed | random | due

-- Pipeline and LLM accounting
pipeline_jobs(id, name, status, stage, subject_id, block_count,
              concepts_created, concepts_updated, concepts_merged,
              edges_proposed, mcqs_generated, error_text, retry_count,
              started_at, finished_at, created_at)
              -- status: queued|running|succeeded|failed|cancelled
pipeline_job_blocks(id, job_id, note_block_id, note_id, text_snapshot,
                    hash_snapshot)
llm_runs(id, job_id, session_id, task, provider, model, prompt_version,
         thinking_level, request_mode, input_tokens, output_tokens,
         cached_tokens, latency_ms, estimated_cost_usd, success,
         error_text, concept_id, created_at)
         -- task: concept_extraction | mcq_generation | question_generation |
         --       evaluation | edge_proposal
         -- request_mode: standard | batch

-- Settings
settings(key, value_json, updated_at)
```

**Indexes:** `notes(study_date)`, `note_blocks(note_id, position)`, `concepts(normalised_name)`, `concept_sources(concept_id)`, `concept_edges(source_concept_id)`, `concept_edges(target_concept_id)`, `review_items(due_at)`, `review_items(concept_id, dimension)` UNIQUE, `mcqs(concept_id, status)`, `review_logs(review_item_id, created_at)`, `llm_runs(created_at)`, `llm_runs(concept_id)`.

**FTS5:** virtual table over `note_blocks.text` and `concepts.canonical_name || definition`.

**Write discipline:** all writes go through a single `Session` factory with a short-lived transaction. The pipeline worker runs in a separate thread within the same process and takes an application-level write lock (`threading.Lock`) around its transactions. Do not open a second connection pool.

---

## 7. Concept identity **[LOCKED]**

This subsystem determines whether the app is usable in three months. Treat it as first-class.

### 7.1 Normalisation

`normalised_name` = lowercase → strip punctuation → collapse whitespace → strip a trailing parenthetical acronym → singularise trailing "s" only when the remainder is ≥4 chars. Store both `canonical_name` (as written) and `normalised_name`.

### 7.2 Matching, in order

For each newly extracted concept:

1. **Exact match** on `normalised_name` against `concepts` or `concept_aliases` → same concept. Add the new name as an alias if different. Done.
2. **Embedding match.** Cosine similarity of `bge-small-en-v1.5` embeddings of `"{name}. {definition}"` against all active concepts in the same Subject.
   - `sim >= 0.92` → **auto-merge.** Record in `concept_merges` with `decided_by='auto'`.
   - `0.82 <= sim < 0.92` → create the concept normally, but also write a `concept_merges` row with `decided_by=NULL` — this is the **merge queue**, surfaced in the Knowledge Graph console.
   - `sim < 0.82` → new concept.
3. Thresholds live in `settings` and are editable from the Settings screen.

Brute-force numpy cosine over all concepts is correct at this scale. Do not add a vector index.

### 7.3 Merge semantics **[LOCKED]**

When concept A merges into concept B:

- A's `canonical_name` and all A's aliases become aliases of B.
- A's `concept_sources` rows repoint to B.
- A's `concept_edges` repoint to B; self-edges and exact duplicates are dropped.
- A's `mcqs` repoint to B.
- For each dimension: if both A and B have a `review_item`, **keep B's FSRS state, keep both items' `review_logs`**, and repoint A's logs to B's item. If only A has one, repoint it to B.
- A is soft-deleted with `status='archived'`; the `concept_merges` row makes it reversible.
- **No note content is ever touched by a merge.**

Merges are reversible from the graph console via `concept_merges.reverted_at`.

### 7.4 Stale concepts **[LOCKED]**

When a note block is edited or deleted, mark its `concept_sources` rows `invalidated_at = now`. If a concept has zero valid sources:

- Set `concepts.status = 'stale'`.
- **Keep scheduling its review items normally.** The user may have reviewed it twenty times; losing the source text does not mean losing the knowledge.
- Surface it in the Knowledge Graph console under "Stale concepts" with the last known definition and which job created it.
- If the user chooses **Delete** there: soft-delete the concept, **hard-delete its MCQs**, suspend its review items. Prose questions need no cleanup since they are generated on demand. Nothing leaves the database.

---

## 8. Pipeline **[LOCKED]**

Triggered only by the **Process notes** button. Scope: a subject, or all subjects.

### 8.1 Job naming

`{adjective}-{animal}` from a built-in wordlist (`amber-lynx`, `quiet-heron`, `brisk-otter`), plus a human date: **`amber-lynx · 22 Aug, 3:40 pm`**. Names need not be globally unique; append a numeric suffix on collision.

### 8.2 Stages

```
queued
  → snapshotting        copy blocks into pipeline_job_blocks
  → chunking            group blocks into coherent units (see 8.3)
  → extracting          LLM: chunks → concepts + edges
  → resolving_identity  local: normalise, embed, match, merge
  → building_graph      insert edges as status='proposed', run cycle check
  → planning_coverage   write coverage_profile, create review_items
  → generating_mcqs     LLM (Batch API): concepts → MCQ pools
  → finalising          mark processed_hash on blocks, write job stats
  → succeeded | failed
```

The worker is a **daemon thread** started at app boot that polls `pipeline_jobs` for `status='queued'` every 2 seconds. Not FastAPI `BackgroundTasks` — those die with the request and lose jobs on restart. Each stage commits its own transaction; a failed job resumes from the last completed stage on retry.

### 8.3 Chunking **[JUDGEMENT]**

Group consecutive note blocks under the same heading, capped at roughly 1200 tokens per chunk with a one-block overlap. Chunks that are a single bullet under 15 words should be merged with their neighbours. Send the Subject/Topic/Subtopic path as context with every chunk.

### 8.4 Cycle detection **[LOCKED]**

`prerequisite_of` edges must form a DAG. Before accepting any such edge, run a DFS from the target to check whether the source is reachable. If it is, insert the edge with `status='proposed'` and flag it `cycle_conflict=true` in the graph console rather than silently dropping it. Only `accepted` prerequisite edges participate in the reachability check.

### 8.5 Job review

Every job has a detail page: what it created, updated, merged, and proposed; which items need attention; its token cost. The graph console can filter by `job_id`. This is how the user does periodic curation without living in the graph.

---

## 9. The two review loops **[LOCKED]**

### 9.1 Quick Practice (MCQ)

**Generation:** eager, at pipeline time, via the **Batch API** (50% discount). Generate 10 MCQs per concept covering `recall` and light `explain`. MCQs may test code snippets, syntax, or which-approach-is-correct, but never require writing code.

**Session:** user picks a count (20 / 30 / 50 / custom) and a scope (all, or specific subjects/topics/tags). Composition:

```
40%  new         concepts never practised, or MCQs never served
40%  failed      MCQs answered incorrectly, most recent first
20%  random      anything else active, weighted toward least-recently-served
```

If a bucket is short, redistribute into `random`. Sessions always fill to the requested count.

**Serving:** shuffle option order every serve. Show a session stopwatch (elapsed, not counting down). Instant feedback after each answer with the explanation.

**Pool hygiene:**
- Retire an MCQ after `consecutive_correct >= 3`.
- When a concept's active pool drops below 4, flag it for regeneration; regenerate on the next pipeline run, seeded with the retired stems so new ones differ.

**Effect on scheduling:** MCQ results write to `mcq_attempts` and feed **practice statistics and the `recall` mastery component only**. They never touch FSRS state, never advance a due date, and never earn a mastery badge on their own. This is deliberate — recognition is not recall.

### 9.2 Revision (prose)

**Generation:** lazy. When a review item is served, generate its question then, with the user's recent failures and previously-seen wordings in the prompt.

**Session:** user picks a count (default 10) and a scope. Composition is by due-state:

```
due and overdue     highest priority first (see 9.4)
due today
new                 review items never reviewed
```

Fill with new items if fewer are due. Show a **session stopwatch**, never a per-question countdown.

**Answering:** a plain textarea. Expected length varies by dimension — `recall` and `explain` want 2–4 sentences; `apply`, `debug`, `synthesis` want a paragraph or two. State the expected length under the question as a hint, not a limit.

**Skip:** an always-visible **"Skip / I don't know"** button. Logs `rating = Again`, shows the expected answer and key points, and moves on. No penalty framing, no confirmation dialog.

**No coding questions.** No LaTeX. Mathematical reasoning is expressed in words.

### 9.3 Evaluation **[LOCKED]**

A separate LLM call from generation. Returns **boolean per key point**, not a float — models are far more consistent at "did they say X? yes/no" than at "rate depth 0–1".

```json
{
  "key_point_hits": [
    {"point": "...", "hit": true},
    {"point": "...", "hit": false}
  ],
  "factually_incorrect_claims": ["..."],
  "misconceptions": ["..."],
  "feedback": "2-4 sentences, direct, addressed to the learner",
  "suggested_rating": "good"
}
```

Rating is derived deterministically in Python, not by the model:

```python
hit_ratio = hits / total_points
if factually_incorrect_claims or misconceptions or hit_ratio < 0.4:
    rating = AGAIN
elif hit_ratio < 0.7:
    rating = HARD
elif hit_ratio < 0.95:
    rating = GOOD
else:
    rating = EASY
```

`suggested_rating` from the model is stored for comparison but not used. If they disagree often, that is useful signal.

**⚠️ Determinism note — this reverses earlier advice.** Google now explicitly recommends **not setting `temperature`, `top_p`, or `top_k` on any Gemini 3.x model**; setting temperature below 1.0 can cause looping and degraded reasoning. Determinism comes from a strict system instruction with explicit rules, a rigid JSON schema, and low `thinking_level` — **not** from sampling parameters. Do not set them anywhere in this codebase.

### 9.4 User override **[LOCKED]**

After every evaluation, two buttons are always present:

- **I actually got this** → forces the rating one step up (`Again`→`Hard`, `Hard`→`Good`, `Good`→`Easy`)
- **No, I was wrong** → forces `Again`

`review_logs` stores `evaluator_rating`, `user_override_rating`, and `final_rating` separately. FSRS consumes `final_rating`. The override is the escape hatch when the grader is being stupid; use it freely.

### 9.5 Immediate retest **[LOCKED]**

At the end of a revision session, any item rated `Again` or `Hard` is offered for immediate retest:

1. **Same question** — the identical wording, to check whether the feedback landed.
2. **Rephrased question** — one fresh generation on the same concept and dimension, different framing.

Both are logged with `is_retest = true` and `retest_of_attempt_id` set.

**Scheduling rule:** the *first* attempt is authoritative for FSRS. A retest may shorten the relearning step (if the item is in relearning and the retest passes, advance the relearning step) but **can never upgrade the original rating or push the due date further out**. Otherwise the retest teaches FSRS that the user knew something they did not.

The item also remains scheduled by FSRS for a later day, as normal.

### 9.6 Anxiety-aware design **[LOCKED]**

The user has flagged that prose questions are the ones they will avoid, and that this app exists partly to work on that. Design accordingly:

- **Never gate Quick Practice behind Revision.** No nags, no "you haven't done your revision" modals, no locked buttons.
- **The dashboard shows prose review as an invitation, not a debt.** Show the count of due items, but never a red badge, never an exclamation mark, never "overdue!" styling. A neutral grey count.
- **Default revision session size is 5, not 10.** Starting is the hard part; make the smallest unit genuinely small. Offer 5 / 10 / 20 / custom.
- **A session of one is a complete session.** Ending a session early records it as finished, not abandoned, and the summary says what was done rather than what was left.
- **No streaks. No combo counters. No "you broke your streak."** Progress is shown as cumulative totals and mastery over time.
- **Feedback wording is factual and specific**, never evaluative about the person. "This missed the role of the reranker" — not "Weak answer."
- **The skip button is as visually prominent as the submit button.** Skipping is a legitimate move, not a failure.

---

## 10. Dimensions, coverage, FSRS **[LOCKED]**

### 10.1 Dimensions

All six exist in v1: `recall`, `explain`, `apply`, `debug`, `synthesis`, `interview`.

- `recall` — covered by MCQs for practice stats and mastery; also has a prose review item.
- `explain`, `apply`, `debug`, `synthesis` — scheduled normally by FSRS from day one.
- `interview` — review items are **created but suspended** (`suspended = true`). A single Settings toggle, **Interview mode**, unsuspends them all. Default off. Turn it on around month 4.

### 10.2 Coverage profile

The extraction LLM proposes which dimensions a concept needs, based on its nature, importance, and difficulty. Stored as `coverage_profile_json`:

```json
{"recall": true, "explain": true, "apply": true, "debug": false,
 "synthesis": false, "interview": true}
```

The profile is **adaptive**: a nightly maintenance pass adds `debug` to any concept whose `apply` dimension has lapsed twice, and adds `synthesis` to any concept with three or more accepted edges whose `explain` and `apply` are both above 80% mastery. Removals are never automatic — only the user removes a dimension.

A `review_item` is created for each `true` dimension. No `review_item` means no scheduling and no cost.

### 10.3 FSRS

Use `py-fsrs` with defaults. Config in `settings`:

```yaml
desired_retention: 0.90
maximum_interval: 365
enable_fuzz: true
learning_steps: ["1m", "10m"]
relearning_steps: ["10m"]
```

**No daily cap.** Session size is chosen per session. The dashboard shows the honest backlog count in neutral styling — the user needs the number, not the pressure.

### 10.4 Queue priority

For each due or new review item:

```python
retrievability   = fsrs.get_retrievability(item, now)     # 0..1
forgetting_risk  = 1 - retrievability
overdue_days     = max(0, (now - item.due_at).days)
overdue_factor   = 1 + log1p(overdue_days) * w_overdue
weakness         = 1 + (item.lapses * w_lapse)
importance       = concept.importance / 3.0               # importance is 1..5
coverage_gap     = w_gap if item.reps == 0 else 0
interview_boost  = w_interview if dimension == "interview" and mode_on else 0

priority = (forgetting_risk * overdue_factor * weakness * importance)
           + coverage_gap + interview_boost
```

Default weights in `settings`: `w_overdue=0.5`, `w_lapse=0.3`, `w_gap=0.4`, `w_interview=0.3`. All editable in Settings.

### 10.5 Mastery and badge decay **[LOCKED]**

Per dimension:

```python
# quality: rolling mean of last 5 attempts' key-point hit ratios
quality = mean(last_5_hit_ratios)

# confidence: penalise thin evidence
confidence = min(1.0, reps / 3.0)

# freshness: FSRS retrievability right now — this is what decays
freshness = fsrs.get_retrievability(item, now)

mastery = quality * confidence * (0.4 + 0.6 * freshness)
```

Badge states, shown per dimension and aggregated per concept:

| State | Condition | Colour |
|---|---|---|
| **Mastered** | `quality >= 0.85` and `freshness >= 0.80` and `reps >= 3` | green |
| **Fading** | `quality >= 0.85` but `freshness < 0.80` | amber |
| **Learning** | `reps >= 1`, not yet mastered | blue |
| **Untested** | `reps == 0` | grey |

Because `freshness` is FSRS retrievability, mastery decays automatically with time — a concept untouched for a month drifts from Mastered to Fading with no separate decay system. One successful review restores it. The concept card shows "Last reviewed: 34 days ago" alongside the badge.

Concept-level mastery is the mean of its active dimensions' mastery, with `apply` and `debug` weighted 1.5× — those distinguish "I remember it" from "I can use it".

---

## 11. Prompt contracts **[LOCKED]**

All prompts live in `backend/prompts/` as versioned files: `concept_extraction_v1.md`, etc. `prompt_version` is written to `llm_runs` and to every generated artefact. Never edit a prompt in place — create `_v2` and switch the config.

All calls use **structured outputs** with a Pydantic-derived JSON schema. All calls are wrapped so that a schema-validation failure retries once with the validation error appended, then fails the job with the raw response stored in `llm_runs.error_text`.

### 11.1 Concept extraction

```
ROLE
Extract durable, learnable concepts from an advanced practitioner's study notes.

CONTEXT
The learner is a working GenAI data scientist. Notes are terse, advanced, and
usually bullet points. They assume background knowledge. Do not extract
beginner-level concepts the notes merely mention in passing.

GRANULARITY — IMPORTANT
Prefer CHUNKY concepts over atomic ones. A concept should be something the
learner would spend two to five minutes explaining in an interview, not a
single fact. Merge closely related bullets into one concept. A typical
20-bullet note should yield 3 to 7 concepts, not 20.

RULES
- Use only what the notes state or directly imply. Do not add outside facts.
- Preserve exact technical terminology as written.
- The definition must be self-contained and understandable without the note.
- Propose prerequisite and relationship edges only where the notes support them.
- If a bullet is too vague to make a concept from, ignore it. Do not invent.
- Attach the source block IDs for every concept.
- Propose a coverage profile based on the concept's nature: procedural and
  system-design concepts need apply and debug; definitional ones may need only
  recall and explain.

Return strict JSON matching the provided schema.
```

Output: `concepts[]` with `name`, `definition`, `importance` (1–5), `difficulty` (1–5), `coverage_profile`, `source_block_ids`, and `edges[]` with `source_name`, `target_name`, `relation_type`, `confidence`.

### 11.2 MCQ generation (Batch API)

```
ROLE
Write multiple-choice questions that test whether the learner recognises and
understands a concept.

RULES
- Generate exactly 10 questions for the given concept.
- Four options each, exactly one correct.
- Distractors must be plausible to someone with partial understanding — common
  confusions, adjacent concepts, subtly wrong conditions. Never absurd.
- Vary what is tested: definition, boundary condition, correct choice of
  approach, correct syntax or code snippet, what breaks if X changes.
- Never require the learner to write code. Reading and choosing code is fine.
- Never make option length or specificity a giveaway.
- Do not reuse or lightly reword any stem in AVOID_STEMS.
- Give a one-sentence explanation for the correct answer and a short rationale
  for why each distractor is wrong.

Return strict JSON matching the provided schema.
```

### 11.3 Prose question generation

Inputs: concept, definition, source note text, prerequisites, related concepts, dimension, target difficulty, last 5 attempts (question + rating + missed points), open misconceptions, previously seen stems.

```
ROLE
Write one retrieval-practice question that makes the learner explain, apply, or
diagnose — not recognise.

GROUNDING
Use only the supplied notes, definition, and prerequisites. Do not introduce
facts the learner has not recorded.

RULES
- Exactly one primary learning objective, unless dimension is synthesis.
- Do not copy the wording of the notes. Do not reveal the answer in the stem.
- Answerable in words. No code to be written. No LaTeX. Mathematical reasoning
  must be expressible in prose.
- Match the dimension: explain wants articulation; apply wants a novel
  scenario; debug wants a symptom to diagnose; synthesis wants two or more
  concepts combined; interview wants a "walk me through" framing.
- If OPEN_MISCONCEPTIONS is non-empty, target one of them directly.
- If PREVIOUS_STEMS is non-empty, use a different context and framing.
- key_points must be 3 to 6 independently checkable claims — each one either
  clearly present in an answer or clearly absent. Not vague qualities.

Return strict JSON matching the provided schema.
```

### 11.4 Evaluation

```
ROLE
Judge whether a learner's written answer contains each required key point.

RULES
- For each key point, decide hit: true or false. Judge meaning, not wording.
  A correct idea expressed differently is a hit. A vague gesture is not.
- List any factually incorrect claim the answer makes.
- List any misconception the answer reveals.
- Write 2 to 4 sentences of feedback: what was solid, what was missing, and the
  single most useful thing to fix. Address the learner directly. Be specific
  and factual. Do not praise or criticise the person.
- Do not grade on length, style, or confidence.

Return strict JSON matching the provided schema.
```

### 11.5 Golden set

`backend/evals/golden/` holds 10 hand-checked note fixtures with expected concept counts and names, and 20 answer/key-point pairs with expected hit patterns. `uv run pytest tests/test_prompts.py` runs them against the live API. Run this before switching any `prompt_version`.

---

## 12. Gemini configuration **[LOCKED]**

Verified against the Gemini API docs on 22 Aug 2026. The `gemini-3` guide page the user linked is now **deprecated** — current guidance is at `/gemini-api/docs/latest-model` and `/gemini-api/docs/whats-new-gemini-3.5`.

### 12.1 API surface

Use the **Interactions API** (`client.interactions.create`) with `google-genai` SDK **v2.0.0+**. It is GA and is where new features land. Do not use the legacy `generateContent` path.

### 12.2 Model assignments

| Task | Model | thinking_level | Mode | Why |
|---|---|---|---|---|
| `concept_extraction` | `gemini-3.7-flash` | `medium` | standard | Quality-critical; a bad extraction poisons everything downstream. |
| `mcq_generation` | `gemini-3.5-flash-lite` | `low` | **batch** | High volume, low difficulty, latency-insensitive. 50% batch discount. |
| `question_generation` | `gemini-3.7-flash` | `low` | standard | Interactive; needs to be good and fast. |
| `evaluation` | `gemini-3.7-flash` | `low` | standard | Consistency matters more than depth. |
| `edge_proposal` | `gemini-3.5-flash-lite` | `low` | standard | Cheap, reviewed by the user anyway. |

All configurable in `config/providers.yaml`. The provider abstraction (`LLMProvider` protocol with `generate_structured`, `generate_text`, `embed`) must be respected — swapping a model is a config change, never a code change.

### 12.3 Parameters — critical

**Do not set `temperature`, `top_p`, `top_k`, or `candidate_count` anywhere.** Google explicitly deprecates these for all Gemini 3.x models; setting temperature below 1.0 can cause looping and degraded reasoning on structured tasks. Use `thinking_level` (`minimal`/`low`/`medium`/`high`) instead of the legacy `thinking_budget`. Never send both.

Determinism comes from strict system instructions and rigid JSON schemas.

### 12.4 Cost optimisation

- **Context caching** for the concept-extraction and MCQ system prompts (they are long and identical across calls). Cache TTL 1 hour, created at the start of a pipeline job.
- **Batch API** for all MCQ generation — half price, and MCQs are never needed within seconds.
- Send only the relevant note chunk and the concept's own history to the question generator, never whole notes.

### 12.5 Pricing table (seed `settings.pricing`)

USD per 1M tokens, as of 22 Aug 2026. Note the introductory rates expire 31 Dec 2026 — put an expiry date in the table so the app can warn when it lapses.

| Model | Input | Output | Batch in | Batch out |
|---|---|---|---|---|
| `gemini-3.7-flash` | 0.75 | 3.75 | 0.375 | 1.875 |
| `gemini-3.6-flash` | 0.75 | 3.75 | 0.375 | 1.875 |
| `gemini-3.5-flash-lite` | 0.30 | 2.50 | 0.15 | 1.25 |
| `gemini-3.1-flash-lite` | 0.25 | 1.50 | 0.125 | 0.75 |

**Expected monthly spend:** roughly **$6–10** at heavy daily use — comfortably inside the ₹3,000 (~$34) cap. Extraction runs about $0.01 per note; a 10-concept MCQ batch about $0.06; each prose question generation plus evaluation about $0.006.

**Use the paid tier, not the free tier.** Google's terms state that free-tier content is used to improve their products; paid-tier content is not. Given these are personal study notes written by someone working in a bank, that distinction is worth $10 a month.

### 12.6 Cost & token view

Gemini's API does **not** expose account spend. It returns `usageMetadata` (input, output, cached token counts) on every call. So:

- Write `input_tokens`, `output_tokens`, `cached_tokens`, `model`, `request_mode` to `llm_runs` on every call.
- Compute `estimated_cost_usd` from the pricing table at write time (so historical rows stay correct when prices change).
- Display in **₹ and $** with a configurable FX rate in Settings.

The **Usage** screen shows: spend this month against the cap with a simple bar; a daily sparkline; a breakdown by task; a breakdown by subject and topic; and a per-concept table — "Transformer attention · 47.2k tokens · ₹18.40 across 23 generations". Label it **"Estimated — from token counts, not billing data"** with a link to the Google Cloud console.

**Soft cap only:** at 80% of the monthly cap, show a banner. At 100%, show a stronger banner and require one confirmation click before each further LLM call. Never hard-block — being unable to study because of a budget setting is worse than the overspend.

---

## 13. Knowledge Graph console **[LOCKED]**

This is a curation workspace, not a decoration. Two panes: the graph on the left, a work queue on the right.

### 13.1 Graph

Cytoscape.js, `cose-bilkent` layout. Nodes coloured by mastery badge state, sized by importance. Edges styled by `relation_type`, dashed when `status='proposed'`.

Interactions: pan, zoom, click to select, double-click to expand neighbours, search, and filters for subject / topic / mastery state / relation type / **job**.

Saved views: Entire graph, Subject, Topic, Concept neighbourhood (2 hops), Weak concepts, Orphan nodes, Missing prerequisites, Stale concepts.

### 13.2 Work queue

Tabs, each with a count badge:

1. **Merge queue** — pairs in the 0.82–0.92 band. Shows both names, definitions, source notes, review history, and similarity. Actions: Merge (choose the surviving name), Keep separate, Skip.
2. **Proposed edges** — accept / reject / flip direction. Cycle conflicts highlighted with the offending path drawn on the graph.
3. **Stale concepts** — zero valid sources. Keep or Delete (see §7.4).
4. **Auto-merged** — a log of `decided_by='auto'` merges from the last 30 days, each with an Undo button. This is how the user builds trust in the thresholds.
5. **Orphans** — no edges at all. Prompt to link or dismiss.

### 13.3 Direct editing

Selecting a node opens an editor: rename (old name auto-becomes an alias), edit definition, edit importance and difficulty, add/remove aliases, toggle coverage dimensions, add or delete edges by searching for another concept, move to a different Subject/Topic/Subtopic, view source notes, view review history, view token cost.

### 13.4 Job filter

A dropdown of jobs by funky name and date. Selecting one dims everything the job did not touch and filters all queue tabs to that job. This is the intended "review every once in a while" workflow.

---

## 14. Screens

```
Header:  [logo] Revise & Learn    Dashboard · Notes · Practice · Revision · Graph    ⌘K   Usage   Settings
Left sidebar:   Subjects → Topics → Subtopics (collapsible, state persisted)
Right sidebar:  contextual (collapsible, state persisted)
```

**Dashboard** — Today (due prose items, new concepts, unprocessed blocks); Continue learning (recent resources with progress); Study next (ranked to-do); Today's notes; Calendar (Apple-style month view with topic pills per day, click to open that day); Progress (concepts, reviews, mastery distribution, retention over time). No streaks.

**Notes** — the editor, with the block indicators from §4.2 and a **Process notes** button in the header showing the unprocessed count. Right sidebar: current resource, pipeline status, concepts extracted from this note, related concepts.

**Practice** — scope and count picker → MCQ runner with stopwatch → summary with per-concept breakdown and a "practise the ones I missed" button.

**Revision** — dashboard (due count in neutral grey, weak areas, history) → scope and count picker → question runner → per-question feedback with override buttons → summary with retest offers.

**Graph** — as §13.

**Usage** — as §12.6.

**Settings** — API key status, model assignments, FSRS parameters, similarity thresholds, priority weights, session defaults, interview mode toggle, FX rate, monthly cap, backup controls, export.

### 14.1 Responsive **[LOCKED]**

Primary use case: a narrow window on the right half of the screen while YouTube or a problem occupies the left.

- Comfortable at **500–750px**. No horizontal scrolling ever.
- Both sidebars auto-collapse below 900px.
- Toolbars collapse to overflow menus; cards stack single-column.
- Graph controls become a floating panel.
- In Notes, the editor is always the dominant element.
- Test explicitly at 500px, 650px, 900px, and 1440px.

### 14.2 Visual direction **[JUDGEMENT]**

Light mode only. Calm and text-forward — this is a place to read and write, not a dashboard product. A warm off-white background rather than pure white, one accent colour drawn from the logo, generous line height in the editor, and a serif or humanist-sans face for note text with a clean sans for UI chrome. Mastery colours must stay legible against the off-white.

### 14.3 Logo

Place the provided file at `assets/logo.svg` (or `.png`, ideally 1024×1024). It is used in the header, as the favicon, and as the macOS app icon. Include `scripts/make_icon.sh` to generate `.icns` from the source image using `sips` and `iconutil`.

### 14.4 Keyboard shortcuts **[LOCKED]**

Minimal only. `⌘K` global search, `⌘S` force save, `⌘Enter` submit answer, `1`–`4` select MCQ option, `Space` next question, `Esc` close modal. Nothing modal, nothing vim-like. A `?` overlay lists them.

---

## 15. API endpoints

```
Notes         GET/POST/PATCH/DELETE  /api/notes
                                     /api/notes/{id}/blocks
              GET                    /api/notes/by-date/{date}
Resources     GET/POST/PATCH/DELETE  /api/resources
              POST                   /api/resources/{id}/open
              GET                    /api/resources/study-next
Hierarchy     GET/POST/PATCH/DELETE  /api/subjects /api/topics /api/subtopics /api/tags
Search        GET                    /api/search?q=            (FTS5 + semantic)
Pipeline      POST                   /api/pipeline/run          {scope}
              GET                    /api/pipeline/jobs
              GET                    /api/pipeline/jobs/{id}
              POST                   /api/pipeline/jobs/{id}/retry
              POST                   /api/pipeline/jobs/{id}/cancel
Practice      POST                   /api/practice/session      {count, scope}
              GET                    /api/practice/session/{id}/next
              POST                   /api/practice/session/{id}/answer
              POST                   /api/practice/session/{id}/finish
Revision      GET                    /api/revision/dashboard
              POST                   /api/revision/session      {count, scope}
              GET                    /api/revision/session/{id}/next
              POST                   /api/revision/session/{id}/answer
              POST                   /api/revision/session/{id}/override
              POST                   /api/revision/session/{id}/retest
              POST                   /api/revision/session/{id}/finish
Concepts      GET/PATCH              /api/concepts /api/concepts/{id}
              GET                    /api/concepts/{id}/neighbors
              GET                    /api/concepts/{id}/history
              POST                   /api/concepts/{id}/aliases
Graph         GET                    /api/graph                 {filters}
              GET                    /api/graph/merge-queue
              POST                   /api/graph/merge
              POST                   /api/graph/merge/{id}/revert
              GET/POST               /api/graph/edges
              POST                   /api/graph/edges/{id}/accept | /reject
              GET                    /api/graph/stale /orphans /missing-prerequisites
Usage         GET                    /api/usage/summary
              GET                    /api/usage/by-concept
              GET                    /api/usage/by-task
Settings      GET/PATCH              /api/settings
Backup        POST                   /api/backup/now
              GET                    /api/backup/list
              POST                   /api/export/markdown
```

---

## 16. Local-first behaviour **[LOCKED]**

**Always works with no network:** open/edit/save notes, browse and edit resources, browse the graph, curate the merge and edge queues, **run Quick Practice** (MCQs are static), review question history, view all logs and stats.

**Requires the API:** running a pipeline job, generating a prose question, evaluating an answer.

If the API is unavailable when a revision session is started, say so plainly and offer Quick Practice instead. Never lose a typed answer — if evaluation fails, store the `question_attempt` with a null evaluator result and a `pending_evaluation` flag, and retry when connectivity returns.

Embeddings run locally, so concept identity and semantic search never depend on the network.

---

## 17. Security, backup, packaging **[LOCKED]**

**Security**
- Bind to `127.0.0.1` only. No `0.0.0.0`, ever.
- API key from the macOS Keychain via the `keyring` package, with `GEMINI_API_KEY` env var as a fallback. Never in SQLite, never in a config file, never logged.
- Settings shows which provider receives note text and which tasks send it.
- No telemetry of any kind.

**Backup**
- Nightly at first launch after 03:00: `VACUUM INTO` a timestamped copy in `~/.revisenlearn/backups/`.
- Retain 7 daily + 4 weekly. A full database is a few tens of MB; this is trivial.
- Manual "Back up now" button in Settings.
- **Export all notes as Markdown** — one folder per Subject/Topic/Subtopic, one file per note, front-matter with date and resource. This is the real insurance policy against the app itself.

**Packaging**

```
./run.sh              # build frontend if stale, start backend, open pywebview window
./run.sh --dev        # Vite dev server on :5173, FastAPI on :8000, hot reload, browser
./run.sh --server     # backend only, no window
```

`run.sh` must: check for `uv`, `uv sync`, run `alembic upgrade head`, build the frontend only when `frontend/src` is newer than `frontend/dist`, download the embedding model on first run with a progress message, then launch.

FastAPI serves the built frontend from `/` and the API from `/api`. One process, one port (8420).

Also ship `scripts/make_app.sh`, which produces a `Revise & Learn.app` bundle whose executable is a two-line shell script calling `run.sh`, with the icon from §14.3. That gives a Dock icon and Spotlight launch without any packaging framework.

---

## 18. Build order **[LOCKED]**

Each phase must be usable on its own before the next begins.

**Phase 1 — Foundation.** Repo layout, `uv` project, FastAPI skeleton, SQLite + WAL + Alembic, full schema from §6, settings table, `run.sh`, pywebview window, React shell with header and sidebars, light-mode design system, logo wired in.
*Done when:* the window opens, the sidebar renders seeded subjects, migrations run clean.

**Phase 2 — Notes and resources.** Subject/Topic/Subtopic CRUD, Tiptap editor with the block set, autosave, block hashing and indicators, resource CRUD with the fast-add flow, resource↔note split view, calendar month view, dashboard v1, FTS5 search, `⌘K`.
*Done when:* the user can do a full day of studying — add a resource, take notes, come back tomorrow and find them.

**Phase 3 — Backup and export.** Nightly `VACUUM INTO`, retention, manual backup, Markdown export.
*Deliberately early:* Phase 4 starts writing data that would hurt to lose.

**Phase 4 — Embeddings and identity.** `fastembed` integration, embeddings table, normalisation, similarity search, merge logic and semantics, alias handling. Test with hand-created concepts before any LLM is involved.
*Done when:* two manually created near-duplicate concepts merge correctly and reversibly.

**Phase 5 — LLM abstraction and pipeline.** `LLMProvider` protocol, Gemini implementation on the Interactions API, `llm_runs` accounting, prompt versioning, job worker thread, staged pipeline through `resolving_identity`, job naming, job detail page, retry.
*Done when:* pressing Process notes turns a real note into correctly deduplicated concepts, and the job page shows what happened and what it cost.

**Phase 6 — Coverage, review items, MCQs.** Coverage profiles, review item creation, MCQ batch generation, pool hygiene, Practice session builder with 40/40/20, MCQ runner with stopwatch, session summary.
*Done when:* the user can do a 50-MCQ session end to end. **This is the first genuinely useful build — expect to live on it for a week before continuing.**

**Phase 7 — FSRS and revision.** `py-fsrs` wiring, priority queue, lazy question generation, prose runner, evaluator with boolean key points, deterministic rating, user override, immediate retest with the scheduling rule from §9.5, append-only `review_logs`, revision dashboard.
*Done when:* a full prose session runs, ratings land in FSRS, and due dates move sensibly.

**Phase 8 — Graph console.** Cytoscape view, filters, saved views, all five work queues, node editing, edge accept/reject, cycle detection UI, job filter.

**Phase 9 — Mastery, usage, polish.** Mastery formulas and badge decay, progress charts, Usage screen, adaptive coverage maintenance pass, responsive audit at all four widths, keyboard shortcuts, `?` overlay.

**Phase 10 — Interview mode.** Unsuspend `interview` review items, interview-specific prompt tuning, a "mock round" session type that serves 5 interview questions across related concepts. **Target: month 4 or later.** Do not build this early.

---

## 19. Testing

- `pytest` for services: identity matching and merge semantics, FSRS wiring, rating derivation, queue priority, mastery formulas, cycle detection, session composition. These are pure functions — test them properly.
- Prompt golden set per §11.5, run manually before any prompt version change.
- One end-to-end smoke test: seed a note → run pipeline against a mocked provider → assert concepts, review items, and MCQs exist.
- No frontend test suite in v1. Manual checks at the four breakpoints.

---

## 20. Deliverables

Alongside the application:

- `README.md` — install, first run, API key setup, daily workflow.
- `DECISIONS.md` — every `[JUDGEMENT]` call made, with reasoning.
- `docs/schema.md` — the data model with an ER diagram.
- `docs/prompts.md` — prompt versions and their change history.
- `config/providers.yaml`, `config/defaults.yaml`.
- `scripts/make_icon.sh`, `scripts/make_app.sh`, `run.sh`.

---

## 21. Known open items

Not blocking v1; revisit after a month of real use.

1. **Similarity thresholds** (0.92 / 0.82) are guesses. The auto-merge log exists precisely so they can be tuned from evidence.
2. **Priority weights** are guesses. `review_logs` captures everything needed to fit them later.
3. **MCQ pool size of 10 and retirement at 3 consecutive correct** are guesses.
4. **Chunky extraction** may still produce too many concepts. If a note yields more than 10, tighten the granularity instruction rather than adding a hard cap.
5. **Adaptive coverage** may inflate review volume. Watch it; the rules are conservative but untested.
6. **Introductory Gemini pricing expires 31 Dec 2026** — input rates double on 1 Jan 2027. The pricing table needs an expiry field and a warning.
