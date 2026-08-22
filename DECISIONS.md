# Decisions

Every `[JUDGEMENT]` call from the spec, plus every place the build had to
choose something the spec did not cover or could not be followed literally.

Spec sections marked `[LOCKED]` are not re-litigated here. Where this document
records a departure, it says so explicitly and why.

---

## 1. Spec `[JUDGEMENT]` sections

### §14.2 Visual direction

> "Light mode only. Calm and text-forward … a warm off-white background rather
> than pure white, one accent colour drawn from the logo, generous line height
> in the editor, and a serif or humanist-sans face for note text with a clean
> sans for UI chrome. Mastery colours must stay legible against the off-white."

Chosen palette, defined as Tailwind v4 theme tokens in `frontend/src/index.css`:

| Token | Value | Role |
|---|---|---|
| `paper` | `#FAF9F6` | Warm off-white page ground |
| `surface` | `#FFFFFF` | Cards, dialogs, header |
| `sunken` | `#F3F1EC` | Hover, code blocks |
| `ink` | `#201E1B` | Warm near-black body text |
| `muted` / `faint` | `#7A736A` / `#A9A198` | Secondary, tertiary |
| `line` | `#E7E2D9` | Warm borders |
| **`accent`** | **`#6B6BDC`** | The one accent |
| `processed` | `#DBEAFE` | §4.2 pale blue — spec-exact |
| `stale` | `#F59E0B` | §4.2 amber |
| `mastery-0…4` | `#C8C2B8` → `#47704A` | Mastery scale |

**Accent provenance.** The supplied `assets/logo.png` is an Ebbinghaus
forgetting-curve diagram: black hand-drawn strokes with periwinkle retention
curves. `#6B6BDC` is sampled from those curves, so the accent genuinely comes
from the logo as the spec asks.

**Typography.** UI chrome uses the system sans stack. Note text uses
`"Iowan Old Style", Palatino, Charter, Georgia, serif` at 17px/1.75 — a
humanist serif that ships with macOS. Every face is a system font, so the app
renders with **no network request for chrome**, which matters because §16
requires it to work fully offline. No webfont is loaded anywhere.

**Mastery legibility.** The scale runs desaturated-clay → amber → green rather
than the usual red→green, because saturated red on a warm off-white reads as an
error state, and §9.6 wants review to feel low-stakes.

### §8.3 Chunking

Not reached. Belongs to Phase 5.

---

## 2. Departures from the build prompt, where the spec overrode it

The prompt said the spec wins on conflict. Three conflicts arose.

### 2.1 API key location — spec §17 `[LOCKED]` won

The prompt asked to "read `creds/gemini_key.txt` on startup". §17 says the key
comes from the macOS Keychain with `GEMINI_API_KEY` as fallback, and is "never
in SQLite, never in a config file, never logged" — a file in `creds/` is
exactly a config file.

**Resolution.** Resolution order is Keychain → `GEMINI_API_KEY` → `creds/`, with
the third documented as a development fallback only. `creds/` is in
`.gitignore`. A one-liner migrates a key into the Keychain:

```bash
uv run python -m revisenlearn.credentials --import-to-keychain
```

The key never reaches SQLite, never crosses the API boundary (only
`{present, source}` does), and never enters a log line. Three tests enforce
this, including one that greps the process's own debug output for the key.

Two follow-on facts: the file is `creds/creds.txt`, not `gemini_key.txt`, and
it holds a sample `curl` command rather than a bare key. Extraction therefore
matches on the **header name** `X-goog-api-key`, not on the key's shape —
Google ships at least two formats (`AIza…` and the newer dotted `AQ.…`, which
is what this repo's key actually uses) and an `AIza`-shaped regex silently
failed on it.

### 2.2 `frontend/` — spec §17 won

The prompt said to ignore `frontend/` as old prototypes. §17 requires the React
app to build from `frontend/src` to `frontend/dist`. The four prototype HTML
files were **moved to `prototypes/`**, not deleted — nothing is thrown away.

### 2.3 Test scope — the prompt's acceptance tests won on scope, spec §19 on form

§19 says "No frontend test suite in v1. Manual checks at the four
breakpoints." The prompt asked for four end-to-end workflow tests including UI
interaction.

**Resolution.** §19's prohibition is read as banning a *component-level* React
unit-test suite, which is not what was asked for. Each workflow is covered
twice: an **API + database** test that is the assertion of record, and a
**browser** test marked `ui` that drives the same built SPA pywebview loads.
`uv run pytest -m "not ui"` runs the full logic suite with no browser at all,
so the browser layer is never load-bearing.

The four breakpoints §14.1 names (500/650/900/1440px) are asserted
automatically rather than checked by hand — a stricter reading of the spec, not
a looser one.

---

## 3. Phase boundary: a Phase 2 slice was built early

**This is the largest judgement call in the build.**

Spec §18 `[LOCKED]` puts hierarchy CRUD, the Tiptap editor, autosave, block
hashing, FTS5 and `⌘K` in **Phase 2**. Phase 1 is only the shell. But the
prompt's Workflows 2, 3 and 4 — creating a subject tree, taking a note that
survives a restart, and searching for it — cannot pass without them.

**Resolution.** All of Phase 1 was built, plus the narrow slice of Phase 2 those
tests require, and Phase 2 was then finished immediately afterwards rather than
left half-done — §18 requires each phase to be usable on its own, and a phase
that exists only as the parts another phase's tests happened to need is not
that.

Phase 2 is now complete: resources with the fast-add flow, the resource↔note
split view, the calendar month view, dashboard v1, the Notes screen with its
Process-notes count, note renaming and additional notes per day, and the §4.2
indicators drawn in the editor.

---

## 4. Implementation choices the spec left open

### Database

- **Integer primary keys**, not UUIDs. Single user, single machine; integers
  keep the FTS5 rowid mapping and the `taggings` polymorphic `target_id` simple.
- **FTS5 tables are standalone**, not `content=''` external-content tables. An
  external-content index needs triggers that fight soft-delete: a row that is
  soft-deleted must leave the index while staying in `note_blocks`. The app
  updates the index explicitly in `db.reindex_block` on every block write. At
  single-user scale the duplicated text is free.
- **Pragmas are applied on a connect-event listener**, in both `db.py` and
  `migrations/env.py`. They cannot be issued inside the migration transaction:
  SQLite refuses to change `journal_mode` from within one, and running it on the
  SQLAlchemy connection autobegins a transaction that silently swallows
  Alembic's own version-table write. That failure mode looked like "downgrade
  does nothing" and cost a debugging round.
- **WAL is set during migration**, so a freshly migrated database is already in
  WAL before the app first opens it.

### API

- **`POST /api/notes/ensure`** is an addition to §15's endpoint list. §4.1 wants
  one note per (Subtopic, day) and §5.1 wants the note "created on the spot if
  it doesn't exist"; a get-or-create endpoint makes that one atomic round trip
  instead of a racy read-then-create in the client.
- **`GET /api/subjects` returns the whole nested tree**, since that is exactly
  what the sidebar renders. Flat lists would cost three requests to draw one
  panel.
- **Soft-delete cascades logically.** Deleting a subject stamps `deleted_at` on
  its topics and subtopics so they leave the tree, but every row survives
  (principle §1.7).
- **Block state is computed server-side** and returned as
  `unprocessed | processed | stale`, so the §4.2 rule lives in one place rather
  than being re-derived in TypeScript.

### Editor

- **Block identity is reconciled by content first, then position.** On save the
  client maps serialised blocks back onto stored rows: identical text claims its
  original row wherever it moved to, and anything left over matches by index.
  This is what makes an edit to a processed block read as **stale** rather than
  as a delete-plus-insert, which would lose `processed_hash` and quietly break
  §4.2.
- **`content_hash` is over normalised text** (whitespace collapsed), so
  reflowing a paragraph does not invalidate the concepts derived from it.
- **A trailing empty paragraph is dropped** before saving — it is Tiptap's
  cursor parking spot, not something the user wrote, and counting it would make
  the "N new" counter wrong on every note.

### Frontend

- **Tailwind v4** with the Vite plugin and CSS-first `@theme` tokens.
- **No dark mode anywhere.** No `prefers-color-scheme` block exists in the
  stylesheet, per §2 `[LOCKED]`.
- **Below 900px the left sidebar overlays** the content rather than compressing
  it, keeping the editor dominant (§14.1) and guaranteeing no horizontal scroll.
- Screens belonging to later phases are rendered but **disabled with a
  "Arrives in Phase N" tooltip**, so the shell shows the app's real shape
  instead of pretending.

### Packaging

- **Dev runs FastAPI on :8000, production on :8420.** Both are literally in
  §17; the Vite proxy targets 8000 and `run.sh --dev` exports `RNL_PORT=8000`.
- **`run.sh` finalises the esbuild install.** npm ≥ 11 defers package install
  scripts, which leaves esbuild without its platform binary and breaks the Vite
  build on a fresh clone. `run.sh` detects the missing binary and rebuilds.

### Dependencies

- **`py-fsrs` → `fsrs`.** §2 names `py-fsrs`; no distribution by that name
  exists on PyPI. The project publishes as `fsrs`. Phase 7 dependency, so this
  is recorded rather than acted on.
- **`requires-python = ">=3.12,<3.14"`.** §2 says 3.12+. The upper bound exists
  because `fsrs` has no 3.14 support and an unbounded range makes the lockfile
  unsolvable.
- **`fastembed`, `google-genai` and `fsrs` are optional extras**, not default
  dependencies, so a Phase 1 install does not pull a ~130MB ONNX model. §17
  asks `run.sh` to download the embedding model on first run; that step is
  written and runs as soon as the `embeddings` extra is installed, and prints a
  one-line skip notice until then.

### Seeding

§18 requires the sidebar to render "seeded subjects", but the prompt's Workflow
1 requires an empty dashboard. A fresh database gets a three-subject starter
tree; `RNL_SEED_SUBJECTS=0` disables it, which is how the test-suite gets a
genuinely empty tree per test. Settings are always seeded, including the §12.5
pricing table with its `expires: 2026-12-31` field so the app can warn when the
introductory rates lapse (§21.6).

---

## 5. Known gaps

- **The logo is a diagram, not a mark.** `assets/logo.png` is a 1404×1462
  Ebbinghaus chart with text labels. It is wired in everywhere §14.3 asks
  (header, favicon, app icon) and loads correctly, but at 28px in the header it
  reads as a grey smudge. A simple square glyph would serve better; the current
  file is kept because it is what was supplied.
- **Search is FTS5 only.** §15 specifies "FTS5 + semantic". The semantic half
  needs local embeddings and arrives in Phase 4. The response shape already
  carries both hit kinds.
- **`⌘S` is bound to `Ctrl/Cmd+S`** and tested with `Control+s`, because
  headless Chromium does not deliver `Meta` chords reliably.

---

## 6. Phase 2 decisions

### Resource type is inferred from the URL

§5.1 gives a five-second budget for adding a resource, and §5 lists nine
resource types. Making the user choose one spends most of that budget on the
least interesting decision, so the type is inferred from the URL (YouTube,
arXiv, `.pdf`, LeetCode, Coursera, …) and can still be overridden. Inference is
a fallback, never an override: an explicit `resource_type` always wins.

### The title probe is a separate endpoint, not part of the create

§5.1 says to "attempt to fetch the page `<title>` for the title field". Doing it
inside `POST /api/resources` would put a network call on the save path, which
principle §1.2 forbids for notes and which the five-second budget forbids here.
`POST /api/resources/probe-title` prefills the field instead, runs in the
background behind a sequence guard so a slow response cannot overwrite a newer
one, and the save never waits for it. Every failure — bad scheme, non-HTML,
4xx/5xx, timeout, no `<title>` — returns a null title and a 200, and the client
falls back to the raw URL.

It reads at most 64KB and stops at `</title>`. `RNL_NO_BROWSER=1` suppresses the
OS opener so the test-suite can exercise `/open` without hijacking the screen.

### Last-used placement lives on the server

§5.1 wants the subject/topic pickers to "default to the last-used values". That
state is stored in `settings.last_used_placement` rather than in browser
storage, so it survives a reinstall and is the same in every window.

### Study-next ranking **[JUDGEMENT]**

§14 asks for a "ranked to-do" but §10.4's priority formula governs *review
items*, not resources. The order is: `in_progress`, then `next`, then `inbox`;
within each, higher priority first, then least-recently-touched. So a
half-finished video outranks a fresh link, and nothing sits at the bottom
forever. Completed and archived work is excluded.

### A resource note and a subtopic note are distinct on the same day

§4.1 gives one note per (Subtopic, day); §5.1 gives a resource "the note for
that resource + today's date". Opening a subtopic and opening a resource filed
under that same subtopic on the same day must therefore not collide.
`POST /api/notes/ensure` keys on `resource_id` when given one, and on
`(subtopic, day)` with `resource_id IS NULL` otherwise. A resource note is
titled after its resource and inherits its placement in the hierarchy.

### Calendar returns only non-empty days

`GET /api/notes/calendar/{YYYY-MM}` returns the days that actually have notes;
the 42-cell grid is drawn client-side. Sending 31 mostly-empty objects to
render a month would be the wrong split. The month-end boundary is computed
rather than assumed so December rolls into January instead of asking for month
13 — there is a test for exactly that.

Two topic pills are shown per day with an overflow count, which is what fits
legibly in a seventh of 500px (§14.1).

### Indicator matching is by normalised text, not by hash

The §4.2 decoration plugin has to answer "which stored block is this editor
node?" for every node on every keystroke. `content_hash` is SHA-256 and
`crypto.subtle.digest` is async, which a synchronous ProseMirror decoration
function cannot await. Normalised text is the same key by a different name.
Duplicate lines are genuinely ambiguous, so they are consumed in document order:
N identical stored blocks light up the first N identical editor nodes.

### Process notes counts new *and* edited blocks

§4.2 makes a processed-then-edited block "stale" — the concepts derived from it
no longer reflect what it says. That is work the pipeline still owes, so the
button's count is `new + edited`, not just `new`. The button is disabled with a
"Phase 5" tooltip rather than hidden, so the Notes screen shows its real shape.

### Two bugs worth recording

Both were caught by the browser tests rather than by reading the code:

- **The editor hydrated on `noteId` alone.** Opening a note whose data was not
  already in the query cache — from the dashboard rather than the sidebar, which
  pre-seeds it — left an empty editor over a non-empty note, and a subsequent
  save would have written that emptiness back. It now hydrates once per note,
  whenever the data actually arrives.
- **Header tabs did not clear the open surface**, so clicking "Dashboard" while
  a note was open appeared to do nothing.

---

## 7. Phase 3 decisions

### `VACUUM INTO`, not a file copy

§17 names `VACUUM INTO` and it is the right primitive: SQLite writes a
consistent, compacted copy from the inside, so it is safe against concurrent
readers and cannot capture a half-written page the way `cp` can. It cannot run
inside a transaction, so the backup connection is opened with `AUTOCOMMIT`, and
it takes the application `write_lock` so it serialises against the pipeline
worker that arrives in Phase 5.

The target path is inlined into the SQL because `VACUUM INTO` has no parameter
binding for it; single quotes are doubled, and the path is ours rather than
user input.

### Retention: last 7 days *with a backup*, not last 7 calendar days **[JUDGEMENT]**

§17 says "retain 7 daily + 4 weekly" without saying what happens when you do
not launch the app for a while. Counting calendar days would mean returning
from a fortnight away, launching once, and finding the history expired — the
opposite of what a backup is for. So the window is the seven most recent *days
that have a backup*, then the four most recent ISO weeks not already covered by
one of those days.

Consequences worth knowing:

- Several manual backups in one day collapse to that day's newest, so pressing
  the button repeatedly cannot consume the whole daily window.
- With a backup every single day, the daily window covers two ISO weeks, so a
  long unbroken run keeps 7 + 3, not 7 + 4. That is the policy working, not a
  bug; there is a test that says so.

Deletion is deliberately narrow. Only files matching `revisenlearn-YYYYMMDD-HHMMSS.db`
are ever considered, so anything else in the backups directory is untouched, and
a freshly taken backup is protected from its own prune.

### Nightly is a startup check, not a scheduler

§17 says "nightly **at first launch** after 03:00". The app is not a daemon, so
there is no timer: on startup it asks whether any backup exists newer than the
most recent 03:00 that has passed, and takes one if not. A failed backup is
logged loudly and swallowed — it must never stop the window opening.
`RNL_NO_NIGHTLY_BACKUP=1` disables it, which is how the test-suite avoids every
app start writing one.

### Export layout **[JUDGEMENT]**

§17 fixes the structure but not the destination, so exports go to
`~/.revisenlearn/exports/export-<timestamp>/` unless a destination is given, and
a relative destination is rejected rather than resolved against whatever
directory the server happened to start in.

Choices inside that:

- Notes with no subject go to `_unfiled/` rather than being skipped. The point
  of an insurance policy is that nothing is dropped for being untidy.
- Filenames are `YYYY-MM-DD-Title.md`, sorted usefully by name alone.
- Path components are sanitised for macOS *and* Windows, including the reserved
  `CON`/`PRN`/`COM1` names, because a restore may well happen on another
  machine years later.
- Two notes sharing a title on the same day (allowed by §4.1) get `-2`, `-3`
  suffixes rather than overwriting each other.
- A `README.md` is written into every export explaining the layout, so the
  folder makes sense to someone who has never run this app.
- Front-matter values are quoted and escaped; a test round-trips them through a
  real YAML parser.

### A bug worth recording

`render_blocks` originally built a flat list of lines and then `zip`ped it
against `blocks` to decide spacing. Any block rendering to more than one line —
a fenced code block, a multi-line quote — desynchronised the two, so blank lines
appeared inside code fences and, worse, `zip` truncated at the shorter sequence
and **silently dropped every block after the first multi-line one**. Data loss,
in the feature whose entire job is preventing data loss.

Each block now renders to exactly one chunk, which may itself be multi-line, and
the spacing pass walks chunks. There is a regression test named after the
failure. Code fences are also sized longer than any backtick run inside them, so
a note containing a fence still round-trips.

---

## 8. Phases 4–6

### fastembed became a default dependency

§16 requires concept identity and semantic search to work with no network, so
the embedding model cannot be optional. Vectors are stored little-endian
float32; cosine is a dot product over L2-normalised rows; matching is
brute-force numpy over the subject, which §7.2 explicitly requires instead of a
vector index.

Identity is tested against the **real** model rather than a stub. §7.2's 0.92
and 0.82 are claims about `bge-small-en-v1.5` specifically, and a fake embedder
would prove nothing about them. Measured: near-identical definitions 0.99, an
acronym against its expansion 0.85, unrelated concepts 0.68 — so the specced
thresholds behave as intended on real data.

### Merge reversal is partial, deliberately

§7.3 makes merges reversible and §6 makes `review_logs` append-only. Those pull
against each other: once A's logs have been repointed to B's review item and B
has been reviewed since, un-repointing them would mean rewriting history that
must never be rewritten. `revert_merge` therefore restores the archived
concept, its aliases and its sources, but does **not** unwind review-item or
edge repointing. Recorded here rather than silently.

### The SDK surface was verified, not assumed

§12.1 mandates `google-genai` v2.0.0+ and `client.interactions.create`. Both
exist (2.19.0). The accepted body keys are `model`, `system_instruction`,
`input`, `response_format`, `generation_config`; the response carries
`output_text` and `usage.total_{input,output,cached}_tokens`. `thinking_level`
goes in `generation_config`, and the provider asserts at call time that
`temperature`, `top_p`, `top_k`, `candidate_count` and `thinking_budget` are
never sent, per §12.3.

### A retry always replays from the first stage

§8.2 says a failed job "resumes from the last completed stage". Extraction
output lives only in the job context — §6 has no table for it — so literally
resuming at, say, `generating_mcqs` would find an empty context and quietly
report success having done nothing. Retry therefore replays from
`snapshotting`, which is idempotent, through `chunking`, which is pure, and
re-runs extraction.

That costs tokens again. It is the honest price of not persisting model output,
and §7.2 identity resolution means the replay deduplicates rather than
duplicating. The failing stage is still recorded on the job so the §8.5 detail
page can say where it broke, and the retry button says plainly that it will
spend again.

### The random bucket excludes the other buckets' leftovers **[JUDGEMENT]**

§9.1's third bucket is "anything else active, weighted toward
least-recently-served". Read naively — sorting by `last_served_at` with
never-served first — the random bucket refills itself with *new* questions and
collapses 40/40/20 into "mostly new". "Anything else" is therefore read as
anything the other two buckets have not claimed: not never-served, not
currently-failed. Only once that pool is exhausted do leftovers fill the gap,
because §9.1 also requires sessions to "always fill to the requested count".

### MCQ generation is not yet on the Batch API

§12.2 assigns `mcq_generation` to the Batch API for the 50% discount. The
current implementation issues standard interactive calls through the same
provider interface and records `request_mode='standard'`, so cost is priced at
standard rates.

This is a real gap against the spec, recorded rather than papered over. The
alternative — recording `request_mode='batch'` while making standard calls —
would have made the Usage screen under-report real spend by half, which is
worse than being late. Batch submission is asynchronous (submit, poll,
retrieve) and cannot be verified without spending money against the live API,
so it is left for a follow-up.

### Practice never touches FSRS

§9.1 is explicit and there is a test that reads every scheduling field before
and after a full session and asserts nothing moved, plus that `review_logs`
stayed empty. Recognition is not recall.

---

## 9. Phases 7–10 and Phase 2b

### §9.5 contains a conflict; the guard wins **[recorded]**

§9.5 asks two things of a passing retest: "advance the relearning step" and
"can never … push the due date further out". In FSRS, advancing a relearning
step *is* a longer interval — with the specced single `["10m"]` step, passing
graduates the card back to Review and schedules it days away. Both cannot hold.

The guard wins, because it is the clause the spec gives a reason for:
"Otherwise the retest teaches FSRS that the user knew something they did not."
A passing retest is therefore logged in full, with `is_retest=true` and
`retest_of_attempt_id` set, but leaves the schedule alone. The test is named
after the conflict so this is not mistaken for a bug later.

### An override rewinds rather than compounds

§9.4 says FSRS consumes `final_rating`. Naively that means calling
`review_card` twice — once for the evaluator's rating, once for the override —
which would double-count the review and, for "I actually got this", leave the
lapse from the first call behind.

The override instead rewinds the review item to the state recorded in the
original log row's `*_before` columns, then re-runs FSRS once with the new
rating. `review_logs` is append-only (§6), so the original row is untouched and
the correction is a second row. Both the evaluator's verdict and the user's
correction survive, which is what §9.4 asks for.

### The `interview` dimension gets its own prompt version

§18's Phase 10 asks for "interview-specific prompt tuning" and §11 forbids
editing a prompt in place. So `question_generation_v2_interview` is a separate
file, selected when the review item's dimension is `interview`, and recorded on
both the `questions` row and its `llm_runs` row.

### The mock round walks the graph

§18 asks for "5 interview questions across related concepts". "Across related
concepts" is doing real work there: five unrelated questions would not feel
like one interview. The round seeds from the highest-priority interview item
and walks its accepted edges two hops out, falling back to plain priority order
when the neighbourhood is thinner than the round — a short graph should still
give a full round.

### Adaptive coverage is a button, not a nightly job

§10.2 describes it as "a nightly maintenance pass". §21.5 says the rules are
"conservative but untested" and may "inflate review volume", and principle §1.3
says "the system never silently spends money or mutates the graph in the
background". Those pull against each other, so it is exposed as an explicit
action in Settings that reports exactly what it changed. Making it automatic is
a one-line change once the rules have earned trust.

### Two clauses of the addendum's §5 are enforced in opposite directions

§5 forbids the progress layer and FSRS mastery from sharing a visual language.
That is tested from both ends: the roadmap payload is asserted to contain no
mastery vocabulary at all, and a 100% progress bar's *computed* fill colour is
asserted to be the accent rather than a mastery green. The mastery palette
appears in exactly two places — the graph console's nodes and the dashboard's
distribution bar — and nowhere in the Roadmap.

### The FTS5 autogenerate hazard, twice

Alembic autogenerate does not know about the FTS5 virtual tables or the five
shadow tables SQLite creates per index, because they are not in SQLModel's
metadata. Generating the Phase 2b migration therefore emitted `DROP TABLE` for
all twelve in `upgrade()` and `CREATE TABLE` for all twelve in `downgrade()` —
the latter referencing `sa.NullType`, which is not a public attribute. The
first broke upgrade; the second broke downgrade.

Both were removed by hand, and `migrations/env.py` now passes an
`include_object` filter so autogenerate never sees them again. Verified by
running autogenerate against a current database and getting zero changes.

### `!(x)?.y` does not mean what it looks like

The `?` overlay guard was written as
`!(e.target as HTMLElement)?.isContentEditable`, which parses as
`(!e.target)?.isContentEditable`. It is now a named `isTyping()` function.
Worth recording because the inline form reads correctly and is wrong.

### Cytoscape sizes its own container

The graph canvas collapsed to zero height twice: first because `h-full` cannot
resolve inside the scrolling `<main>`, which has no definite height, and then
because Cytoscape sets `position: relative` inline on its container, cancelling
`absolute inset-0`. The fix is a definite height on the console
(`100vh` minus the header) and a directly sized container. Measured in the
browser rather than guessed a third time.

---

## 10. The notes-first rework (consolidated addendum)

A single document superseded the lessons/todos addendum and two addenda that
never reached this repo. It is a rework, not a patch, and these are the calls
it forced.

### `checklist_items` is a projection, and the API refuses to pretend otherwise

§2 **[LOCKED]**: "This table has no dedicated CRUD UI. The only way to create
or edit a checklist item is by typing or checking a box inside the note
editor." So `lesson_items` is gone and the endpoints that wrote it are gone
with it. What remains is `GET` plus one `PATCH` that toggles `checked` — and
that toggle writes the **note block**, then re-derives the row. There is no
code path that writes a `checklist_items` row directly, which is the only way
to guarantee the two never diverge.

The visible cost is in the Roadmap: its inline "add item" input and its
Tab-into-item-mode had to go, because both created rows out of thin air. Tab
now opens the new lesson's note, which is where items are actually written.

### A lesson's note is found without `study_date`

§3 asks for "ONE note that grows over time … not a new note per day". The
`ensure_note` lesson branch therefore deliberately does not filter on
`study_date` — the one query in that function that ignores the date. A comment
says so, because it looks like a bug next to the three branches above it.

### Navigation is a real route, in the hash

§3 asks for "real page navigation (e.g. route `/lessons/{id}`), not an inline
pane swap". This is a one-window local app with no router, so the route lives
in `location.hash`: opening a lesson pushes `#/lessons/12`, Back works, and a
reload lands on the same note. Adding a router for one route would have been
more machinery than the requirement.

### Name and chevron are separate targets

§5 asks for Notion's distinction exactly: the chevron expands, the name
navigates, and Subject/Topic/Subtopic names "do nothing". A row's name at
those three levels is therefore a `<span>`, not a button — it has no hover
state and no pointer cursor, because an inert control that looks clickable is
worse than no control. Double-clicking it expands, as a concession to muscle
memory.

### One endpoint for dragging and for "Move to…"

A drag and a picked destination are the same operation: a new parent and an
index. `POST /api/tree/move` handles both for all four levels and renumbers
the siblings densely, so ordering never depends on what the `sort_order`
values happened to be before. A lesson may not straddle two topics: a subtopic
that belongs elsewhere is a 400, not a silent correction.

### The right panel defaults, but never overrides

§6 wants Checklist to be the default "whenever the lesson has checklist items"
and also that a finishing job "never force-switches the tab away from what
they're doing". Both hold: the default is applied until the user picks a tab
for that note, and a finished job raises a badge and nothing else.

### `- [ ] ` needed its own input rule

StarterKit turns `- ` into a bullet the moment the space lands, so TaskItem's
own `[ ] ` rule can never fire — a `taskItem` cannot be wrapped inside a
`listItem`. A small extension converts the enclosing list instead, which also
gives the bare `[ ] ` form for free. Without it, §2's literal syntax would
have produced a bullet reading "[ ] text".

### The pipeline stopped paying for its own punctuation

Date dividers are written by the app, and an empty checkbox is a line the user
has not written yet. Neither is worth an input token, so both are excluded
from what "Process notes" sends — visible in the new block preview, which
lists exactly what a run would spend money on.

### Migrations were not transactional, and that cost real data

The rework shipped with three faults that every test missed for the same
reason: the suite only ever migrated **empty** databases.

1. Alembic's SQLite batch mode rebuilds a table by copying it, dropping the
   original and renaming. With `PRAGMA foreign_keys=ON`, `DROP TABLE notes`
   fails — `note_blocks`, `checklist_items` and `concept_sources` all point at
   it. An empty database has no such rows and no such failure. Enforcement is
   now off **for migration connections only**, which is what the Alembic docs
   prescribe for batch mode, and `PRAGMA foreign_key_check` runs inside the
   same transaction before it commits.
2. pysqlite emits `BEGIN` before DML but never before DDL, so each
   `CREATE`/`DROP`/`ALTER` committed as it ran. When (1) failed halfway, the
   completed steps stayed and `alembic_version` still claimed the old
   revision — a database that could never migrate again, because the next
   attempt hit "table checklist_items already exists". `env.py` now disables
   pysqlite's transaction handling and issues its own `BEGIN`, and commits
   explicitly: Alembic assumes non-transactional DDL on SQLite and will not
   commit for us, so without that last line the whole migration rolled back
   silently, with exit code 0.
3. `_convert_lesson_items` wrote `notes.lesson_id` before the migration added
   that column — the conversion ran *before* the ALTERs. It never failed only
   because with no rows to convert it returned early. It also never wrote the
   `checklist_items` rows for what it converted, which would have left those
   items invisible until the note was next saved.

`tests/test_migrations.py` migrates a database that has content in it, and
asserts that a deliberate mid-migration failure leaves nothing behind. That is
the test that was missing.

### The Keychain had to become hideable

`test_settings_reports_key_presence_but_never_the_key` asserts the app says
"absent" when there is no key. The harness clears the environment and points
`RNL_CREDS_DIR` at an empty directory, but it cannot un-import a key from the
developer's own macOS Keychain — and once the key was imported there, the test
started failing on this machine and only this machine. `RNL_NO_KEYCHAIN=1`
makes "no key anywhere" a state the suite can actually reach.

---

## 11. Pages everywhere, and the Roadmap as the way in

The user's direction, after using the rework: *"let's keep just roadmap as a
way to add notes, no other place, this is now the centralised way to access
notes"* and *"a Notion type interface where everything is a page and pages
under pages — when I open a page I should be able to see all the pages under
it too"*. That overrides parts of the consolidated addendum, which is fine:
the addendum was a plan, and this is the person using the thing.

### Every level is a page, so page notes are continuous

Spec §4.1 says "one note per (Subtopic, day)". Addendum §3 already broke that
for lessons — one continuous note, with a date divider on the first edit of a
new day — because a note per session fragments a subject you return to. That
reasoning does not stop at lessons, and a page whose note changes identity at
midnight is not a page. So Subject, Topic and Subtopic notes are continuous
too, and `GET /api/pages/{kind}/{id}` is the one endpoint that answers "what
is this page, what is above it, what is inside it".

Resource notes are the exception and stay per-resource-per-day: §5.1's split
view is a reading session, not a page.

### Names navigate, at every level

Addendum §5 made Subject/Topic/Subtopic names inert because only a Lesson had
a note. Now that every level has one, every name navigates — which is the
Notion behaviour §5 was pointing at ("clicking the **name** navigates to open
that page"). The chevron still expands in place.

### Delete lives in the Roadmap only

Hover-trash on every sidebar row was in the addendum, and it was wrong in
practice: the sidebar is what you move through, and a delete control on a row
you are passing over is an accident waiting to happen. The Roadmap is where
you go to change the shape of things, so deletion lives there, behind one
confirmation, for all four levels. Todos gained one too — but only for
standalone todos: a lesson or a checklist item shown on that board lives
somewhere else, and deleting it from a view of it would be deleting it from
the wrong place.

### One refresh, not fifteen invalidations

"Every time I add something to the app I should be able to refresh it and it
should be updated everywhere." Each mutation used to invalidate the two or
three query keys its author remembered, which is how a screen ends up stale
after an edit somewhere else. `useRefreshEverything` invalidates the whole set
in one call, and mutations use it instead of listing keys.

### Code blocks carry their language

Highlighting is bundled (lowlight with sixteen grammars, Python and SQL
first), never fetched. The language is a column on `note_blocks`, because a
note should reopen in the grammar it was written in rather than one guessed
from the text. The built-in fence rule only fires in a plain paragraph, so a
note that is mostly bullets — which is most notes here — could not start a
code block without leaving the list by hand; a small input rule lifts out of
the list and opens the block wherever the cursor is.

### `google-genai` was an optional extra, so the LLM never worked

`run.sh` runs `uv sync`, which does not install extras, and the client was
declared under `[project.optional-dependencies]`. The first real "Process
notes" therefore failed with *cannot import name 'genai' from 'google'* after
queueing a job and charging nothing. Without it the pipeline cannot run and
prose revision has no questions (§16), so it is not optional and is now a
core dependency.

### The reset script left dangling references

`reset_content.py` cleared notes and note blocks but not `pipeline_job_blocks`,
which points at both. Harmless until migrations started verifying referential
integrity before committing — then the next launch failed the check and the
app would not start. The script clears them now and runs
`PRAGMA foreign_key_check` itself before declaring success. Jobs survive:
they are the record of what was spent, and cost history is not content.

---

## 12. What is not built

Honest list, so nothing here is a surprise.

- **The golden set (§11.5).** `backend/evals/golden/` is empty. Building it
  means spending real money on real notes, and the fixtures should be the
  user's own material. Until it exists, every prompt version bump is
  unverified. This is the most important outstanding item.
- **MCQ generation is not on the Batch API** (§12.2). Standard calls, priced
  and recorded as standard, so cost is truthful rather than claiming a discount
  that was not taken. See §8 above.
- **Context caching** (§12.4) for the long extraction and MCQ system prompts is
  not implemented. `cached_tokens` is recorded on every run, so the saving will
  be visible the moment it is.
- **Saved graph views are computed, not stored.** §13.1 lists eight views and
  all eight work, but "saved" in the sense of the user naming their own is not
  built.
- **No prose questions are generated offline** (§16). That is by design — the
  spec says revision requires the API — and the UI says so plainly and points
  at Quick Practice instead.
- **The data reset (consolidated addendum §0) has not been run.** It ships as
  `scripts/reset_content.py`, which backs the database up first and needs
  `--yes`. Deleting the user's live database is theirs to trigger, not mine.
- **Checklist nesting is one level, and only from the editor.** The schema and
  the projection carry `parent_block_id`, and Tiptap nests with Tab, but the
  right panel's "+ add item" always appends at the top level.
