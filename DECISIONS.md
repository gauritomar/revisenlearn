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
