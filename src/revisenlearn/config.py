"""Paths, ports and runtime configuration.

Everything here is overridable by environment variable so the test-suite can
point the app at a scratch database without touching the user's real one.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

#: Spec §17 — one process, one port.
DEFAULT_PORT = 8420
#: Spec §17 — bind to loopback only. Never 0.0.0.0.
HOST = "127.0.0.1"

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent.parent
CONFIG_DIR = REPO_ROOT / "config"
ASSETS_DIR = REPO_ROOT / "assets"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def data_dir() -> Path:
    """The user's permanent record lives here (spec §17)."""
    root = Path(os.environ.get("RNL_DATA_DIR", Path.home() / ".revisenlearn"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def backups_dir() -> Path:
    d = data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    override = os.environ.get("RNL_DB_PATH")
    if override:
        p = Path(override)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return data_dir() / "revisenlearn.db"


def database_url() -> str:
    return f"sqlite:///{db_path()}"


def port() -> int:
    return int(os.environ.get("RNL_PORT", DEFAULT_PORT))


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def defaults() -> dict:
    return load_yaml("defaults.yaml")


def providers() -> dict:
    return load_yaml("providers.yaml")
