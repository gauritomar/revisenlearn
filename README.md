# Revise & Learn

A local-first study app. You write notes; the app turns them into durable
concepts, then schedules them for review. Single user, single machine, no cloud,
no auth, no Docker.

**Status: Phase 1 (Foundation) complete.** See [Build status](#build-status).

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

---

## API key setup

No model is called anywhere in Phase 1. The key is resolved and its *presence*
reported, nothing more.

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

From Phase 5, a **Process notes** button turns what you wrote into concepts, and
Phases 6–7 add the two review loops.

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

uv run pytest                # all 36 tests
uv run pytest -m "not ui"    # API + database only, no browser needed
uv run pytest -m ui          # browser tests (needs: uv run playwright install chromium)

uv run alembic upgrade head
uv run alembic revision --autogenerate -m "what changed"
```

Optional dependency groups, installed at the phase that needs them:

```bash
uv sync --extra embeddings   # fastembed, Phase 4 (~130MB model on first use)
uv sync --extra llm          # google-genai, Phase 5
uv sync --extra fsrs         # fsrs, Phase 7
```

### Layout

```
src/revisenlearn/     FastAPI app, SQLModel schema, credentials, desktop window
  api/                routers: meta, hierarchy, notes, search, settings
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
| 2 | Notes and resources | partial — notes, hierarchy, FTS5 and `⌘K` are in; resources, calendar and dashboard v1 are not |
| 3 | Backup and export | not started |
| 4 | Embeddings and identity | not started |
| 5 | LLM abstraction and pipeline | not started |
| 6 | Coverage, review items, MCQs | not started |
| 7 | FSRS and revision | not started |
| 8 | Graph console | not started |
| 9 | Mastery, usage, polish | not started |
| 10 | Interview mode | not started |

Phase 2 is partially complete because the Phase 1 acceptance tests exercise
note-taking and search. See `DECISIONS.md`.

---

## Documents

- [`DECISIONS.md`](DECISIONS.md) — every `[JUDGEMENT]` call, with reasoning
- [`docs/schema.md`](docs/schema.md) — the data model and an ER diagram
- [`docs/prompts.md`](docs/prompts.md) — prompt versions (empty until Phase 5)
- `revise-and-learn-v1-spec.md` — the specification. It is the source of truth.
