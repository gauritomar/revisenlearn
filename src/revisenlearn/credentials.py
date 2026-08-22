"""API key resolution.

Spec §17 **[LOCKED]**: "API key from the macOS Keychain via the `keyring`
package, with `GEMINI_API_KEY` env var as a fallback. Never in SQLite, never in
a config file, never logged."

The build prompt asked for the key to be read from ``creds/``. That is a config
file, which the spec forbids as a storage location, so it is supported only as a
last-resort *development* fallback and is reported as such. The key is never
returned to the frontend, never written to the database, and never logged — only
its presence and the source it came from.

No network calls are made in Phase 1. This module resolves the key and stops.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .config import REPO_ROOT

log = logging.getLogger(__name__)

KEYRING_SERVICE = "revisenlearn"
KEYRING_USERNAME = "gemini_api_key"

#: Candidate dev-fallback files, in order. The prompt named ``gemini_key.txt``;
#: the repo actually ships ``creds.txt`` holding a sample curl command.
CREDS_CANDIDATES = ("gemini_key.txt", "creds.txt")

#: The value of an ``X-goog-api-key`` header, however it is quoted. Google has
#: shipped at least two key formats (``AIza...`` and the newer ``AQ.<dotted>``),
#: so this deliberately matches on the header name rather than the key's shape.
_HEADER_RE = re.compile(
    r"""x-goog-api-key \s* : \s* ["']? \s* ([^\s"'\\]+)""",
    re.IGNORECASE | re.VERBOSE,
)
#: ``?key=...`` in a query string, the other way Google's samples pass it.
_QUERY_RE = re.compile(r"""[?&]key=([^\s"'&\\]+)""")


@dataclass(frozen=True)
class KeyStatus:
    """What we know about the key, minus the key itself."""

    present: bool
    source: str  # keychain | env | creds-file | absent

    def describe(self) -> str:
        if not self.present:
            return "Gemini API key: absent (no LLM features until configured)"
        return f"Gemini API key: present (source: {self.source})"


def _from_keyring() -> str | None:
    # The Keychain is machine-level: a test harness can clear the environment
    # and point RNL_CREDS_DIR somewhere empty, but it cannot un-import a key
    # the developer stored on their own Mac. This makes "no key anywhere" a
    # state the suite can actually reach.
    if os.environ.get("RNL_NO_KEYCHAIN") == "1":
        return None
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception as exc:  # keyring backend missing or locked
        log.debug("keyring lookup failed: %s", type(exc).__name__)
        return None


def _from_env() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or None


def _from_creds_file() -> str | None:
    creds_dir = Path(os.environ.get("RNL_CREDS_DIR", REPO_ROOT / "creds"))
    for name in CREDS_CANDIDATES:
        path = creds_dir / name
        if not path.exists():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for pattern in (_HEADER_RE, _QUERY_RE):
            match = pattern.search(text)
            if match:
                return match.group(1)
        # A file containing nothing but the key, no curl wrapper.
        stripped = text.strip()
        if stripped and "\n" not in stripped and len(stripped) > 20:
            return stripped
    return None


def resolve_api_key() -> tuple[str | None, KeyStatus]:
    """Return ``(key, status)``. The key is for callers that will use it; the
    status is safe to log and to expose over the API."""
    for source, getter in (
        ("keychain", _from_keyring),
        ("env", _from_env),
        ("creds-file", _from_creds_file),
    ):
        key = getter()
        if key:
            return key, KeyStatus(present=True, source=source)
    return None, KeyStatus(present=False, source="absent")


def key_status() -> KeyStatus:
    """Presence check only — the key itself is discarded."""
    _, status = resolve_api_key()
    return status


def log_key_status_on_startup() -> KeyStatus:
    status = key_status()
    log.info(status.describe())
    if status.source == "creds-file":
        log.warning(
            "Key was read from a file in creds/. Spec §17 wants it in the macOS "
            "Keychain. Run: python -m revisenlearn.credentials --import-to-keychain"
        )
    return status


def import_to_keychain() -> bool:
    """Move a key found in env/creds into the Keychain, per spec §17."""
    key, status = resolve_api_key()
    if not key:
        print("No key found in keychain, GEMINI_API_KEY, or creds/.")
        return False
    if status.source == "keychain":
        print("Key already in the macOS Keychain. Nothing to do.")
        return True
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key)
    print(f"Imported key from {status.source} into the macOS Keychain.")
    print("You may now delete creds/ — it is already in .gitignore.")
    return True


if __name__ == "__main__":
    import sys

    if "--import-to-keychain" in sys.argv:
        raise SystemExit(0 if import_to_keychain() else 1)
    print(key_status().describe())
