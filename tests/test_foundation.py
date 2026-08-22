"""Phase 1 foundation: migrations, schema, pragmas, seeding, credentials.

Spec §18 Phase 1 is *done when* "the window opens, the sidebar renders seeded
subjects, migrations run clean". These tests cover the parts of that which are
not a user workflow.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from conftest import REPO_ROOT, start_app

#: Every table named in spec §6.
SPEC_TABLES = {
    "subjects", "topics", "subtopics", "tags", "taggings",
    "notes", "note_blocks",
    "resources",
    "concepts", "concept_aliases", "concept_merges", "concept_sources",
    "concept_edges", "embeddings",
    "mcqs", "mcq_attempts",
    "questions", "question_attempts",
    "review_items", "review_logs", "misconceptions",
    "sessions", "session_items",
    "pipeline_jobs", "pipeline_job_blocks", "llm_runs",
    "settings",
}

#: Every index named in spec §6.
SPEC_INDEXES = {
    "ix_notes_study_date",
    "ix_note_blocks_note_position",
    "ix_concepts_normalised_name",
    "ix_concept_sources_concept_id",
    "ix_concept_edges_source",
    "ix_concept_edges_target",
    "ix_review_items_due_at",
    "ix_mcqs_concept_status",
    "ix_review_logs_item_created",
    "ix_llm_runs_created_at",
    "ix_llm_runs_concept_id",
}


def _alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "RNL_DB_PATH": str(db_path)},
        capture_output=True,
        text=True,
    )


def test_migrations_run_clean_from_scratch(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    result = _alembic(db, "upgrade", "head")

    assert result.returncode == 0, result.stderr
    assert db.exists()
    assert "Running upgrade" in result.stderr

    current = _alembic(db, "current")
    assert "(head)" in current.stdout, current.stdout


def test_migrations_downgrade_and_reupgrade(tmp_path: Path) -> None:
    """A migration that cannot be reversed is a migration you cannot trust."""
    db = tmp_path / "roundtrip.db"
    assert _alembic(db, "upgrade", "head").returncode == 0

    down = _alembic(db, "downgrade", "base")
    assert down.returncode == 0, down.stderr

    conn = sqlite3.connect(db)
    remaining = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    # Only Alembic's own bookkeeping table survives a full downgrade.
    assert remaining == {"alembic_version"}, remaining

    assert _alembic(db, "upgrade", "head").returncode == 0


def test_full_spec_schema_exists(tmp_path: Path) -> None:
    db = tmp_path / "schema.db"
    assert _alembic(db, "upgrade", "head").returncode == 0

    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()

    missing = SPEC_TABLES - tables
    assert not missing, f"Tables from spec §6 are missing: {sorted(missing)}"

    missing_idx = SPEC_INDEXES - indexes
    assert not missing_idx, f"Indexes from spec §6 are missing: {sorted(missing_idx)}"


def test_review_items_concept_dimension_is_unique(tmp_path: Path) -> None:
    """Spec §6 marks review_items(concept_id, dimension) UNIQUE — one FSRS
    state per (Concept x Dimension) pair."""
    db = tmp_path / "unique.db"
    assert _alembic(db, "upgrade", "head").returncode == 0

    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO review_items (concept_id, dimension, lapses, reps, suspended, "
        "created_at, updated_at) VALUES (1, 'recall', 0, 0, 0, '2026-01-01', '2026-01-01')"
    )
    try:
        conn.execute(
            "INSERT INTO review_items (concept_id, dimension, lapses, reps, suspended, "
            "created_at, updated_at) VALUES (1, 'recall', 0, 0, 0, '2026-01-01', '2026-01-01')"
        )
        raise AssertionError("duplicate (concept_id, dimension) was accepted")
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()


def test_fts5_tables_exist(tmp_path: Path) -> None:
    """Spec §6: FTS5 virtual table over note_blocks.text and concepts."""
    db = tmp_path / "fts.db"
    assert _alembic(db, "upgrade", "head").returncode == 0

    conn = sqlite3.connect(db)
    sql = {
        r[0]: (r[1] or "")
        for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    }
    conn.close()

    assert "note_blocks_fts" in sql
    assert "concepts_fts" in sql
    assert "fts5" in sql["note_blocks_fts"].lower()
    assert "fts5" in sql["concepts_fts"].lower()


def test_database_is_in_wal_mode(tmp_path: Path) -> None:
    """Spec §6 [LOCKED]: WAL, busy_timeout=5000, foreign_keys=ON."""
    db = tmp_path / "wal.db"
    assert _alembic(db, "upgrade", "head").returncode == 0

    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()


def test_app_enforces_foreign_keys_and_busy_timeout(app) -> None:
    """The pragmas must be live on the connections the app actually uses."""
    from revisenlearn import config, db as db_module

    os.environ["RNL_DB_PATH"] = str(app.db_path)
    db_module.reset_engine()
    engine = db_module.get_engine()
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
    db_module.reset_engine()
    assert config.HOST == "127.0.0.1"


def test_settings_table_is_seeded(app, client) -> None:
    """Spec §18 Phase 1 includes the settings table; §12.5 seeds pricing."""
    body = client.get("/api/settings").json()
    values = body["values"]

    assert "pricing" in values
    assert values["pricing"]["per_1m_tokens"]["gemini-3.7-flash"]["input"] == 0.75
    # Spec §21.6 — the introductory rates lapse and the app must be able to warn.
    assert values["pricing"]["expires"] == "2026-12-31"

    # Spec §7.2 thresholds must be editable from Settings, so they live in the
    # settings table rather than only in code.
    assert values["similarity_thresholds"] == {"auto_merge": 0.92, "merge_queue": 0.82}
    assert values["autosave_debounce_ms"] == 800


def test_seeded_subjects_render_in_the_tree(seeded_app) -> None:
    """Spec §18: Phase 1 is done when 'the sidebar renders seeded subjects'."""
    import httpx

    with httpx.Client(base_url=seeded_app.base_url, timeout=30) as c:
        subjects = c.get("/api/subjects").json()

    assert len(subjects) >= 3
    names = {s["name"] for s in subjects}
    assert "GenAI" in names

    genai = next(s for s in subjects if s["name"] == "GenAI")
    assert any(t["name"] == "Retrieval" for t in genai["topics"])


def test_api_never_returns_the_key_itself(app, client) -> None:
    """Spec §17 [LOCKED]: the key is never in SQLite, a config file, or a log.
    It must not cross the API boundary either."""
    meta = client.get("/api/meta").json()
    assert set(meta["api_key"]) == {"present", "source"}

    settings = client.get("/api/settings").json()
    assert set(settings["api_key"]) == {"present", "source"}

    stored = app.query("SELECT value_json FROM settings")
    blob = " ".join(row[0] for row in stored)
    assert "AIza" not in blob


def test_key_resolution_order_prefers_env_over_creds_file(tmp_path: Path) -> None:
    """Keychain, then GEMINI_API_KEY, then the creds/ dev fallback."""
    creds = tmp_path / "creds"
    creds.mkdir()
    (creds / "creds.txt").write_text(
        "curl \"https://generativelanguage.googleapis.com/v1/models\" \\\n"
        "  -H 'X-goog-api-key: AIzaSyFAKEfilekeyFAKEfilekeyFAKE00' \\\n"
    )

    script = (
        "import revisenlearn.credentials as c;"
        "k, s = c.resolve_api_key();"
        "print(s.source, k)"
    )

    # No env var -> falls through to the creds file, and parses it out of curl.
    env = {**os.environ, "RNL_CREDS_DIR": str(creds)}
    env.pop("GEMINI_API_KEY", None)
    # Neutralise any real Keychain entry on the developer's machine.
    env["PYTHONPATH"] = str(tmp_path / "stub")
    (tmp_path / "stub").mkdir()
    (tmp_path / "stub" / "keyring.py").write_text(
        "def get_password(*a, **k):\n    return None\n"
    )

    out = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO_ROOT, env=env,
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    source, key = out.stdout.split()
    assert source == "creds-file"
    assert key == "AIzaSyFAKEfilekeyFAKEfilekeyFAKE00"

    # With the env var set, it wins.
    env["GEMINI_API_KEY"] = "AIzaSyFAKEenvkeyFAKEenvkeyFAKE0000"
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO_ROOT, env=env,
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    source, key = out.stdout.split()
    assert source == "env"
    assert key == "AIzaSyFAKEenvkeyFAKEenvkeyFAKE0000"


def test_key_parsing_handles_both_google_key_formats(tmp_path: Path) -> None:
    """Google ships at least two key shapes: the classic ``AIza...`` and the
    newer dotted ``AQ....``. The repo's own creds/ file uses the latter, so
    matching on the key's shape rather than the header name silently fails."""
    stub = tmp_path / "stub"
    stub.mkdir()
    (stub / "keyring.py").write_text("def get_password(*a, **k):\n    return None\n")

    cases = {
        "AIzaSyCLASSICkeyCLASSICkeyCLASSIC01": (
            "curl 'https://x' -H 'X-goog-api-key: {key}' \\\n"
        ),
        "AQ.Ab8RN6Jmodern_key-shape.WITH.dots99": (
            "curl \"https://x\" \\\n  -H 'X-goog-api-key: {key}' \\\n"
        ),
        "AIzaSyQUERYSTRINGkeyQUERYSTRING0001": (
            "curl 'https://generativelanguage.googleapis.com/v1/models?key={key}'\n"
        ),
    }

    for index, (expected, template) in enumerate(cases.items()):
        creds = tmp_path / f"creds-{index}"
        creds.mkdir()
        (creds / "creds.txt").write_text(template.format(key=expected))

        env = {**os.environ, "RNL_CREDS_DIR": str(creds), "PYTHONPATH": str(stub)}
        env.pop("GEMINI_API_KEY", None)
        out = subprocess.run(
            [sys.executable, "-c",
             "import revisenlearn.credentials as c;"
             "k, s = c.resolve_api_key();"
             "print(s.source, k)"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True,
        )
        assert out.returncode == 0, out.stderr
        source, parsed = out.stdout.split()
        assert source == "creds-file"
        assert parsed == expected, f"parsed {parsed!r}, expected {expected!r}"


def test_startup_logs_key_presence_but_never_the_key(tmp_path: Path) -> None:
    """Spec §17: 'never logged'."""
    creds = tmp_path / "creds"
    creds.mkdir()
    secret = "AIzaSyFAKEsecretFAKEsecretFAKE1234"
    (creds / "creds.txt").write_text(f"-H 'X-goog-api-key: {secret}'\n")

    db = tmp_path / "logs.db"
    port_env = {
        **os.environ,
        "RNL_DB_PATH": str(db),
        "RNL_CREDS_DIR": str(creds),
        "RNL_SEED_SUBJECTS": "0",
    }
    port_env.pop("GEMINI_API_KEY", None)

    out = subprocess.run(
        [sys.executable, "-c",
         "import logging, sys;"
         "logging.basicConfig(level=logging.DEBUG, stream=sys.stdout);"
         "import revisenlearn.credentials as c;"
         "print('status:', c.log_key_status_on_startup().describe())"],
        cwd=REPO_ROOT, env=port_env, capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    combined = out.stdout + out.stderr
    assert "present" in combined
    assert secret not in combined, "the API key leaked into the logs"


def test_no_llm_call_is_made_in_phase_1(app, client) -> None:
    """Principle §1.3 / the Phase 1 brief: no LLM calls at all."""
    client.get("/api/meta")
    client.get("/api/subjects")
    assert app.query("SELECT count(*) FROM llm_runs")[0][0] == 0
