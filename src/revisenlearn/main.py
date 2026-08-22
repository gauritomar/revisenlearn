"""FastAPI application.

Spec §17: one process, one port (8420). FastAPI serves the built frontend from
``/`` and the API from ``/api``. Bound to 127.0.0.1 only — never 0.0.0.0.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from . import config
from .api import api_router
from .backup import run_nightly_if_due
from .credentials import log_key_status_on_startup
from .db import session_scope
from .migrate import upgrade_to_head
from .seed import seed_all

log = logging.getLogger(__name__)

LOGO_PATH = config.ASSETS_DIR / "logo.png"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    )
    if os.environ.get("RNL_SKIP_MIGRATIONS") != "1":
        upgrade_to_head()
    with session_scope() as session:
        seed_all(session)
    # Phase 1 resolves the key and reports its presence. No LLM call is made
    # until Phase 5.
    log_key_status_on_startup()

    # Spec §17 — nightly backup at first launch after 03:00. The app is not a
    # daemon, so this is a startup check rather than a schedule. It never
    # raises: a failed backup must not stop the window opening.
    taken = run_nightly_if_due()
    if taken is not None:
        log.info("Nightly backup taken: %s", taken.name)
    log.info("Revise & Learn ready on http://%s:%s", config.HOST, config.port())
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Revise & Learn",
        version=config.load_yaml("defaults.yaml").get("version", "0.1.0"),
        lifespan=lifespan,
        # No auth, single user, loopback only — but keep the docs off the
        # default path so they never shadow an SPA route.
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.include_router(api_router)

    @app.get("/logo.png", include_in_schema=False)
    def logo() -> FileResponse:
        return FileResponse(LOGO_PATH, media_type="image/png")

    # Favicon is the same mark (spec §14.3).
    @app.get("/favicon.png", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(LOGO_PATH, media_type="image/png")

    dist = config.FRONTEND_DIST
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"),
                  name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(request: Request, full_path: str):
        """Serve the SPA shell for any non-API path (client-side routing)."""
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        index = dist / "index.html"
        if not index.exists():
            return JSONResponse(
                {
                    "detail": "Frontend not built.",
                    "fix": "Run ./run.sh (it builds when frontend/src is newer "
                           "than frontend/dist), or: cd frontend && npm install "
                           "&& npm run build",
                },
                status_code=503,
            )
        candidate = (dist / full_path) if full_path else index
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)

    return app


app = create_app()
