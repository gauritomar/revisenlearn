"""The pywebview desktop window.

Uvicorn runs in a daemon thread inside this process; pywebview owns the main
thread because macOS requires the UI on thread 0. One process, one port
(spec §17).
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.error
import urllib.request

from . import config

log = logging.getLogger(__name__)

#: Spec §14.1 — the app lives in a narrow window beside YouTube or a problem
#: set. Comfortable at 500–750px, so that is where it opens.
WINDOW_WIDTH = 720
WINDOW_HEIGHT = 900
MIN_SIZE = (420, 560)


def _serve() -> None:
    import uvicorn

    uvicorn.run(
        "revisenlearn.main:app",
        host=config.HOST,
        port=config.port(),
        log_level="info",
    )


def wait_for_health(url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.15)
    return False


def run_desktop() -> int:
    import webview

    base = f"http://{config.HOST}:{config.port()}"

    thread = threading.Thread(target=_serve, name="uvicorn", daemon=True)
    thread.start()

    if not wait_for_health(f"{base}/api/health"):
        log.error("Backend did not become healthy on %s", base)
        return 1

    webview.create_window(
        "Revise & Learn",
        base,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=MIN_SIZE,
        background_color="#FAF9F6",  # the warm off-white from §14.2
        text_select=True,
    )
    webview.start()
    return 0
