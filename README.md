# Revise & Learn

A local-first study app. You write notes; the app turns them into durable
concepts, then schedules them for review. Single user, single machine, no cloud,
no auth, no Docker.

**Status: complete.** All ten phases plus the addendum's Phase 2b. See [Build status](#build-status).

---

## Install

Requires macOS, [uv](https://docs.astral.sh/uv/) and Node 18+.

```bash
brew install uv node
```

Then, from the repo root:

```bash
./run.sh
```

That single command checks for `uv`, syncs Python dependencies, runs
`alembic upgrade head`, builds the frontend if `frontend/src` is newer than
`frontend/dist`, and opens the desktop window.

### Other modes

```bash
./run.sh            # build if stale, start backend, open the window
./run.sh --dev      # Vite on :5173, FastAPI on :8000, hot reload, browser
./run.sh --server   # backend only, no window — http://127.0.0.1:8420
```

Production is one process on one port (8420) serving both the API and the built
frontend. The server binds to `127.0.0.1` only.

### A Dock icon

```bash
./scripts/make_app.sh
```

Produces `dist/Revise & Learn.app`, whose executable is a two-line script
calling `run.sh`. Drag it to `/Applications`. The icon is generated from
`assets/logo.png` by `scripts/make_icon.sh` using `sips` and `iconutil`.

---

## First run

The first launch creates `~/.revisenlearn/revisenlearn.db` (SQLite, WAL mode),
runs every migration, seeds the settings table, and seeds a small starter
subject tree so the sidebar is not empty. Rename or delete those subjects
freely — they are only a starting point.

Migrations run inside one transaction: if any step fails, the database is left
exactly as it was, and the error says why. A launch that reports a migration
error has changed nothing.

Your data lives in `~/.revisenlearn/`. That directory is the whole app state;
back it up and you have backed up everything.

```
~/.revisenlearn/
  revisenlearn.db     the database
  backups/            automatic nightly copies, 7 daily + 4 weekly
  exports/            Markdown exports you asked for
```

Two maintenance scripts live in `scripts/`. Both print what they would do and
change nothing until you add `--yes`, and both take a backup first:

| Script | What it does |
|---|---|
| `reset_content.py` | Clears subjects, topics, subtopics, lessons, notes and resources, keeping the schema, settings and everything you have learned |
| `adopt_notes_into_lessons.py` | Gives each pre-rework note a Lesson, so the sidebar can open it — notes written before lessons existed are otherwise reachable only from the calendar |

---

## API key setup

No model is called anywhere yet — the first LLM call arrives in Phase 5. The
key is resolved and its *presence* reported, nothing more.

The key is read from, in order:

1. the **macOS Keychain** (service `revisenlearn`, account `gemini_api_key`);
2. the **`GEMINI_API_KEY`** environment variable;
3. a file in **`creds/`** — a development fallback only.

The spec requires the Keychain. To move a key there from either fallback:

```bash
uv run python -m revisenlearn.credentials --import-to-keychain
```

Then delete `creds/`. It is already in `.gitignore`.

The key is never written to the database, never returned by the API, and never
logged — startup logs only `present`/`absent` and which source it came from.

---

## Daily workflow

1. Open the app. It lands on the **Roadmap**, which is the whole curriculum
   and the way into every note. The Dashboard (the logo, or the nav) shows the
   calendar first, then what is due and what you were working on.
2. Everything is a page: a Subject, a Topic, a Subtopic and a Lesson all open
   the same way and all have a note. Clicking a name anywhere — Roadmap,
   sidebar, breadcrumb — opens that page, and a page lists the pages inside
   it, so you can add a Topic from inside a Subject without going anywhere.
3. A page has **one continuous note** that grows over time, with a date
   divider dropped in automatically on the first edit of a new day.
4. Write. Bullets are the fast path:
   - `- ` a bullet, `# ` a heading, `> ` a quote
   - `- [ ] ` a checklist item, which appears in the right panel, the Roadmap
     and Todos — all three write back to the same line in the note
   - ` ```python ` (or `sql`, `javascript`, …) a syntax-highlighted code
     block, and it works inside a list too
   - a URL becomes a resource on its own, no dialog
   - **+ New section** adds a heading with bullets under it, at the top or the
     end — notes arrive out of order, so both ends are one click away
5. Autosave is debounced 800ms after you stop typing, plus on blur, plus every
   30 seconds; `⌘S` forces it.
6. `⌘K` searches everything you have written, and adds a subject, topic,
   subtopic or lesson anywhere in the tree without expanding it first.

Adding and deleting live in the Roadmap, where rows also drag to reorder and
subjects and topics fold away. The sidebar is for getting around: it has no
delete, because a trash icon on a row you are only passing through is an
accident waiting to happen.

A lesson's status is one button, cycling **not started → in progress (amber)
→ done (green) → come back to this (red)**. Todos use the same two colours and
are yours alone — nothing in the app writes to them.

Any page can carry the link it came from — an article, a lecture, a LeetCode
problem — shown under its title. That link belongs to the page, so it survives
the note being rewritten and is never sent to the model as content.

Or start from a resource, which is the faster daily entry point: **Add
resource**, paste a link, press Enter. Click it to get a split view — the
resource, its status and progress slider on the left, today's note for it on
the right. The dashboard's **Study next** ranks what to pick up, and the
calendar shows what you wrote on any day.

When you have written enough, press **Process notes** in the header — it
counts every pending block in the app, wherever you are. It shows the
**sections** it would send, grouped exactly as the chunker groups them (a
heading and what is under it), each with a tick. Untick anything you have
written down but not studied yet: it stays unticked until you say otherwise,
shows as *parked* in the editor, and is never paid for. Each note in the list
links to the page it came from, before it
spends anything, then extracts concepts from your notes, deduplicates them
against what you already know, and generates a pool of multiple-choice
questions per concept. **Runs** shows what each job created and exactly what it
cost.

**Practice** is a 20/30/50-question multiple-choice session with a stopwatch:
`1`–`4` to answer, `Space` for the next. It feeds your statistics only — it
never moves a review date, because recognition is not recall.

**Revision** is the one that does. Written answers, marked against key points,
with a rating derived in Python rather than by the model. Five is the default
session and a session of one still counts. Both override buttons are always
there for when the grader is being stupid.

**Resources** is a blank page. Write links, notes to self, anything you want
to come back to — the same keys as any other note, and nothing else. It is
never sent to the model and never counts as a day's study: a reading list is
not something to be examined on.

**Todos** is yours alone — only what you put there, never a lesson or a
checklist item. One checkbox per row, which ticks a todo off; press **Select**
when you want to act on several at once, and the row's checkbox becomes a
selection box with Mark done, Mark open and Delete above it.

**Practice** and **Revision** both open with a set per place you have studied —
lesson or subtopic, most recently written first, with its question count and
your score on it. Somewhere you have written about but never generated
questions for gets a *Generate a test* button, which is a model call and says
so.

The **Dashboard** opens with the calendar, and under it *Revise today*: what
is due, grouped by the day you wrote it ("studied 3 days ago"), with that
material's questions one click away and your score on them beside it. FSRS
picks the intervals; the app just says which day's work has come back.

**Roadmap** tracks what you have worked through — lessons and their items, with
percentage bars. Deliberately a different visual language from mastery: a full
bar there means you ticked every box, not that you know it. **Todos** is the
flat "what's left" view across everything.

**Graph** is the curation workspace: merge queue, proposed edges, stale
concepts, auto-merges you can undo, and orphans. **Usage** shows what all of it
has cost.

### Backup and export

A compacted copy of the database is written automatically at the first launch
after 03:00 each day, into `~/.revisenlearn/backups/`. Seven daily and four
weekly copies are kept. **Settings → Back up now** takes one on demand.

**Settings → Export all notes as Markdown** writes one folder per
Subject/Topic/Subtopic and one file per note, each with YAML front-matter
giving its date and, where relevant, its resource. Those are plain files that
need nothing from this app to read — which is the point. Export before anything
risky.

To restore: quit the app and copy a backup over `~/.revisenlearn/revisenlearn.db`
(remove any `-wal` and `-shm` files beside it first).

### Keyboard

| Key | Does |
|---|---|
| `⌘K` | Global search |
| `⌘S` | Force save |
| `Esc` | Close modal |

`⌘Enter` (submit answer), `1`–`4` (select MCQ option) and `Space` (next
question) arrive with the review loops in Phases 6 and 7.

---

## Development

```bash
uv sync                      # Python deps
cd frontend && npm install   # frontend deps

uv run pytest                # all 430 tests
uv run pytest -m "not ui"    # API + database only, no browser needed
uv run pytest -m ui          # browser tests (needs: uv run playwright install chromium)

uv run alembic upgrade head
uv run alembic revision --autogenerate -m "what changed"
```

Optional dependency groups, installed at the phase that needs them:

```bash
uv sync --extra llm          # google-genai, needed for real Gemini calls
uv sync --extra fsrs         # fsrs, Phase 7
```

`fastembed` is a default dependency from Phase 4 on: concept identity and
semantic search must work offline. The first run downloads a ~130MB ONNX
model.

**No test ever calls a real model.** The suite runs with
`RNL_LLM_PROVIDER=mock`; only pressing **Process notes** in the app spends
anything.

### Layout

```
src/revisenlearn/     FastAPI app, SQLModel schema, credentials, desktop window
  api/                routers: meta, hierarchy, notes, resources, search, settings
migrations/           Alembic; the full §6 schema plus the FTS5 tables
frontend/src/         React 18 + TypeScript + Vite + Tailwind, light mode only
tests/                end-to-end workflow tests (real server, real DB, real browser)
config/               providers.yaml, defaults.yaml — no secrets
scripts/              make_icon.sh, make_app.sh
prototypes/           the original static HTML mockups, kept for reference
docs/                 schema.md, prompts.md
```

---

## Build status

Phases are from spec §18. Each must be usable on its own before the next
begins.

| Phase | | |
|---|---|---|
| 1 | Foundation | **done** |
| 2 | Notes and resources | **done** |
| 2b | Lessons, todos, roadmap (addendum) | **done** |
| 3 | Backup and export | **done** |
| 4 | Embeddings and identity | **done** |
| 5 | LLM abstraction and pipeline | **done** |
| 6 | Coverage, review items, MCQs | **done** |
| 7 | FSRS and revision | **done** |
| 8 | Graph console | **done** |
| 9 | Mastery, usage, polish | **done** |
| 10 | Interview mode | **done** |

Phase 10 was specced for "month 4 or later"; interview mode is built but
defaults off, exactly as §10.1 requires. Turn it on in Settings when you are
ready for it.

---

## Documents

- [`DECISIONS.md`](DECISIONS.md) — every `[JUDGEMENT]` call, with reasoning
- [`docs/schema.md`](docs/schema.md) — the data model and an ER diagram
- [`docs/prompts.md`](docs/prompts.md) — prompt versions (empty until Phase 5)
- `revise-and-learn-v1-spec.md` — the specification. It is the source of truth.
