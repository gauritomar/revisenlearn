#!/usr/bin/env bash
#
# Revise & Learn launcher (spec §17).
#
#   ./run.sh            build frontend if stale, start backend, open the window
#   ./run.sh --dev      Vite on :5173, FastAPI on :8000, hot reload, browser
#   ./run.sh --server   backend only, no window
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

MODE="app"
case "${1:-}" in
  --dev)     MODE="dev" ;;
  --server)  MODE="server" ;;
  "")        MODE="app" ;;
  -h|--help)
    sed -n '3,9p' "$0" | sed 's/^# \{0,1\}//'
    exit 0 ;;
  *)
    echo "Unknown option: $1" >&2
    echo "Usage: ./run.sh [--dev | --server]" >&2
    exit 2 ;;
esac

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
info()  { printf '  %s\n' "$*"; }
die()   { printf '\033[31mError: %s\033[0m\n' "$*" >&2; exit 1; }

bold "Revise & Learn"

# --- 1. uv -----------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  die "uv is not installed.
  Install it with:  brew install uv
  or:               curl -LsSf https://astral.sh/uv/install.sh | sh"
fi
info "uv $(uv --version | awk '{print $2}')"

# --- 2. Python dependencies ------------------------------------------------
info "Syncing Python dependencies..."
uv sync --quiet

# --- 3. Migrations ---------------------------------------------------------
info "Running migrations..."
uv run alembic upgrade head 2>&1 | sed -n 's/^INFO  \[alembic.runtime.migration\] \(Running.*\)/    \1/p' || \
  die "alembic upgrade failed"
info "Database at head."

# --- 4. Embedding model ----------------------------------------------------
# Spec §17 asks run.sh to download the embedding model on first run. The model
# belongs to Phase 4 and lives behind the `embeddings` extra, so this step is a
# no-op until that extra is installed (see DECISIONS.md).
if uv run --quiet python -c "import fastembed" >/dev/null 2>&1; then
  info "Checking embedding model (BAAI/bge-small-en-v1.5)..."
  uv run python - <<'PY'
from fastembed import TextEmbedding
name = "BAAI/bge-small-en-v1.5"
print(f"    Loading {name} (first run downloads ~130MB, please wait)...", flush=True)
TextEmbedding(model_name=name)
print("    Embedding model ready.", flush=True)
PY
else
  info "Embedding model: skipped (Phase 4 — install with: uv sync --extra embeddings)"
fi

# --- 5. Frontend -----------------------------------------------------------
build_frontend_if_stale() {
  if ! command -v npm >/dev/null 2>&1; then
    die "npm is not installed. Install Node with: brew install node"
  fi
  if [ ! -d frontend/node_modules ]; then
    info "Installing frontend dependencies..."
    (cd frontend && npm install --silent)
  fi
  # npm >= 11 defers package install scripts, which leaves esbuild without its
  # platform binary and breaks the Vite build on a fresh clone.
  if ! ls frontend/node_modules/@esbuild/*/bin/esbuild >/dev/null 2>&1; then
    info "Finalising esbuild install..."
    (cd frontend && npm rebuild esbuild --silent)
  fi

  # Build only when frontend/src is newer than frontend/dist (spec §17).
  local newest_src
  newest_src=$(find frontend/src frontend/index.html frontend/package.json \
                    frontend/vite.config.ts frontend/tsconfig.json \
                    -type f -newer frontend/dist/index.html 2>/dev/null | head -1 || true)

  if [ ! -f frontend/dist/index.html ] || [ -n "$newest_src" ]; then
    info "Building frontend..."
    (cd frontend && npm run build --silent >/dev/null)
    info "Frontend built."
  else
    info "Frontend up to date."
  fi
}

# --- 6. Launch -------------------------------------------------------------
case "$MODE" in
  dev)
    # No dist build in dev — Vite serves from source with hot reload.
    if [ ! -d frontend/node_modules ]; then
      info "Installing frontend dependencies..."
      (cd frontend && npm install --silent)
    fi
    export RNL_PORT=8000                # spec §17
    bold "Dev mode"
    info "FastAPI  http://127.0.0.1:8000"
    info "Vite     http://127.0.0.1:5173  (open this one)"

    uv run uvicorn revisenlearn.main:app \
      --host 127.0.0.1 --port 8000 --reload --reload-dir src &
    API_PID=$!
    # Stop the backend whenever Vite exits, however it exits.
    trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM
    (cd frontend && npm run dev -- --open)
    ;;

  server)
    build_frontend_if_stale
    bold "Server mode"
    info "http://127.0.0.1:${RNL_PORT:-8420}"
    exec uv run python -m revisenlearn --server
    ;;

  app)
    build_frontend_if_stale
    bold "Opening window..."
    exec uv run python -m revisenlearn
    ;;
esac
