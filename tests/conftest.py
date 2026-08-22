"""End-to-end test harness.

Every test here runs the real application: a real uvicorn process, the real
Alembic migrations, a real SQLite file, and (for the `ui` tests) the real built
frontend in a real browser. Nothing is mocked and nothing is monkeypatched.

Each test gets its own scratch database, so the user's own
``~/.revisenlearn/revisenlearn.db`` is never touched.
"""

from __future__ import annotations

import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

STARTUP_TIMEOUT = 60.0


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_for_health(base_url: str, proc: subprocess.Popen, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out = (proc.stdout.read() if proc.stdout else "") or ""
            raise RuntimeError(
                f"Server exited early with code {proc.returncode}.\n{out[-4000:]}"
            )
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=1) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
            time.sleep(0.15)
    out = (proc.stdout.read() if proc.stdout else "") or ""
    raise RuntimeError(f"Server never became healthy ({last_error}).\n{out[-4000:]}")


@dataclass
class AppProcess:
    """A running instance of the app, plus the database it is writing to."""

    proc: subprocess.Popen
    base_url: str
    db_path: Path

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Read the database directly — the assertion of record for 'is it
        actually persisted?'."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()


def start_app(
    db_path: Path,
    *,
    seed_subjects: bool = False,
    extra_env: dict[str, str] | None = None,
) -> AppProcess:
    """Boot a real server subprocess against ``db_path``.

    Migrations run inside the app's own startup, so a successful boot is itself
    proof that ``alembic upgrade head`` works from a cold database.
    """
    port = free_port()
    env = {
        **os.environ,
        "RNL_DB_PATH": str(db_path),
        "RNL_PORT": str(port),
        # Keep the starter tree out of the way so workflow assertions see only
        # what the test itself created.
        "RNL_SEED_SUBJECTS": "1" if seed_subjects else "0",
        # Tests must never pick up the developer's real key from creds/ or the
        # Keychain; credential resolution is asserted separately.
        "RNL_CREDS_DIR": str(db_path.parent / "no-creds"),
        # Never let a test open a real browser window on the user's screen.
        "RNL_NO_BROWSER": "1",
        # Backups are opt-in per test; otherwise every app start would
        # write one and the retention tests would be fighting noise.
        "RNL_NO_NIGHTLY_BACKUP": "1",
        # Keep exports and backups inside the test's own tmp_path.
        "RNL_DATA_DIR": str(db_path.parent / "data"),
        "PYTHONUNBUFFERED": "1",
        **(extra_env or {}),
    }
    env.pop("GEMINI_API_KEY", None)

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "revisenlearn.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        wait_for_health(base_url, proc, STARTUP_TIMEOUT)
    except Exception:
        proc.kill()
        raise
    return AppProcess(proc=proc, base_url=base_url, db_path=db_path)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "revisenlearn.db"


@pytest.fixture
def app(db_path: Path):
    """A running app on a fresh, empty database."""
    instance = start_app(db_path)
    try:
        yield instance
    finally:
        instance.stop()


@pytest.fixture
def seeded_app(db_path: Path):
    """A running app with the first-run starter subject tree."""
    instance = start_app(db_path, seed_subjects=True)
    try:
        yield instance
    finally:
        instance.stop()


@pytest.fixture
def client(app: AppProcess):
    """An httpx client bound to the running app."""
    import httpx

    with httpx.Client(base_url=app.base_url, timeout=30) as c:
        yield c


# --------------------------------------------------------------------------
# Browser fixtures
# --------------------------------------------------------------------------

def _frontend_built() -> bool:
    return (FRONTEND_DIST / "index.html").exists()


@pytest.fixture(scope="session")
def browser():
    """A Chromium instance, or a skip if Playwright is not usable here.

    The UI tests drive the same built SPA that pywebview loads, over the same
    loopback URL. Automating the pywebview WKWebView window itself is not
    supported by any driver; the page under test is byte-identical.
    """
    playwright = pytest.importorskip(
        "playwright.sync_api", reason="playwright is not installed"
    )
    if not _frontend_built():
        pytest.skip("frontend/dist is missing — run ./run.sh or npm run build")

    try:
        pw = playwright.sync_playwright().start()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Playwright failed to start: {exc}")

    try:
        instance = pw.chromium.launch()
    except Exception as exc:
        pw.stop()
        pytest.skip(
            f"Chromium is not installed for Playwright ({exc}). "
            "Install it with: uv run playwright install chromium"
        )

    try:
        yield instance
    finally:
        instance.close()
        pw.stop()


def _open_page(browser, instance: AppProcess):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    p = context.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(instance.base_url, wait_until="networkidle")
    try:
        yield p
    finally:
        # A React crash must fail the test rather than hide behind a missing
        # element assertion.
        assert not errors, f"Uncaught JavaScript errors: {errors}"
        context.close()


@pytest.fixture
def page(browser, app: AppProcess):
    """A browser page pointed at the running app, sized per spec §14.1."""
    yield from _open_page(browser, app)


@pytest.fixture
def seeded_page(browser, seeded_app: AppProcess):
    """A browser page against an app with the first-run starter tree."""
    yield from _open_page(browser, seeded_app)


# --------------------------------------------------------------------------
# In-process database session
#
# The identity subsystem (spec §7) is mostly pure logic over the database, and
# §19 says to test that properly rather than only through HTTP. These tests run
# against a real migrated SQLite file in-process, which is both faster and more
# direct than driving a server.
# --------------------------------------------------------------------------

@pytest.fixture
def session(tmp_path: Path, monkeypatch):
    import subprocess as sp

    db = tmp_path / "inproc.db"
    monkeypatch.setenv("RNL_DB_PATH", str(db))
    monkeypatch.setenv("RNL_DATA_DIR", str(tmp_path / "data"))

    result = sp.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env={**os.environ, "RNL_DB_PATH": str(db)},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    from revisenlearn import db as db_module

    db_module.reset_engine()
    with db_module.session_scope() as s:
        yield s
    db_module.reset_engine()
