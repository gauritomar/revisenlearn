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

Your data lives in `~/.revisenlearn/`. That directory is the whole app state;
back it up and you have backed up everything.

```
~/.revisenlearn/
  revisenlearn.db     the database
  backups/            automatic nightly copies, 7 daily + 4 weekly
  exports/            Markdown exports you asked for
```

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

1. Open the app. The dashboard shows what is due and what you were working on.
2. Pick a subtopic in the left sidebar. Today's note opens, created on the spot
   if it does not exist yet.
3. Write. Bullets are the fast path. Autosave is debounced 800ms after you stop
   typing, plus on blur, plus every 30 seconds; `⌘S` forces it.
4. `⌘K` searches everything you have written.

Or start from a resource, which is the faster daily entry point: **Add
resource**, paste a link, press Enter. Click it to get a split view — the
resource, its status and progress slider on the left, today's note for it on
the right. The dashboard's **Study next** ranks what to pick up, and the
calendar shows what you wrote on any day.

When you have written enough, press **Process notes**. It asks before it
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
