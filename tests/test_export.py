"""Markdown export (spec §17 **[LOCKED]**).

"This is the real insurance policy against the app itself" — so the bar is that
the output is readable years from now on a machine that has never run this app.
These tests read the files back off disk as plain text.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

TODAY = dt.date.today().isoformat()


def _tree(client) -> dict:
    subject = client.post("/api/subjects", json={"name": "GenAI"}).json()
    topic = client.post(
        "/api/topics", json={"subject_id": subject["id"], "name": "Retrieval"}
    ).json()
    subtopic = client.post(
        "/api/subtopics", json={"topic_id": topic["id"], "name": "Hybrid search"}
    ).json()
    return {"subject": subject, "topic": topic, "subtopic": subtopic}


def _note_with(client, subtopic_id: int, blocks: list[dict]) -> dict:
    note = client.post("/api/notes/ensure", json={"subtopic_id": subtopic_id}).json()
    client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [
            {"id": None, "position": i, **b} for i, b in enumerate(blocks)
        ]},
    )
    return note


def _export(client, tmp_path: Path, name: str = "out") -> Path:
    dest = tmp_path / name
    result = client.post(
        "/api/export/markdown", json={"destination": str(dest)}
    ).json()
    assert result["path"] == str(dest)
    return dest


# --------------------------------------------------------------------------
# Block rendering — pure, so test it directly
# --------------------------------------------------------------------------

def _render(*pairs: tuple[str, str]) -> str:
    from revisenlearn.export import render_blocks
    from revisenlearn.models import NoteBlock

    blocks = [
        NoteBlock(note_id=1, position=i, block_type=kind, text=text,
                  content_hash="x")
        for i, (kind, text) in enumerate(pairs)
    ]
    return render_blocks(blocks)


def test_every_block_type_renders() -> None:
    """Spec §4.1 fixes the block set; all of it must survive the export."""
    out = _render(
        ("heading1", "Retrieval"),
        ("paragraph", "Two families of scorer."),
        ("heading2", "Sparse"),
        ("bullet_list_item", "BM25"),
        ("bullet_list_item", "Exact terms"),
        ("heading3", "Dense"),
        ("numbered_list_item", "Embed"),
        ("numbered_list_item", "Search"),
        ("quote", "Retrieval is the bottleneck."),
        ("code_block", "score = bm25 + alpha * cosine"),
        ("divider", ""),
        ("paragraph", "End."),
    )

    assert "# Retrieval" in out
    assert "## Sparse" in out
    assert "### Dense" in out
    assert "- BM25\n- Exact terms" in out          # one list, not two
    assert "1. Embed\n2. Search" in out            # numbering counts up
    assert "> Retrieval is the bottleneck." in out
    assert "```\nscore = bm25 + alpha * cosine\n```" in out
    assert "\n---\n" in out


def test_no_block_is_lost_after_a_multi_line_block() -> None:
    """Regression: a code block renders to three lines but is one block. An
    earlier version zipped blocks against lines, which misaligned the spacing
    pass and silently dropped every block after the first multi-line one — data
    loss in the feature whose whole job is preventing data loss."""
    out = _render(
        ("code_block", "x = 1"),
        ("divider", ""),
        ("paragraph", "Must not disappear"),
        ("quote", "Nor this"),
        ("paragraph", "Nor this either"),
    )

    assert "Must not disappear" in out
    assert "> Nor this" in out
    assert "Nor this either" in out
    assert "\n---\n" in out
    # And the fence contains only the code.
    assert "```\nx = 1\n```" in out


def test_a_code_block_containing_a_fence_round_trips() -> None:
    out = _render(("code_block", "```\nnested\n```"))
    assert out.startswith("````\n")
    assert "nested" in out


def test_numbering_restarts_after_a_break() -> None:
    out = _render(
        ("numbered_list_item", "One"),
        ("numbered_list_item", "Two"),
        ("paragraph", "Interruption."),
        ("numbered_list_item", "One again"),
    )
    assert "1. One\n2. Two" in out
    assert "1. One again" in out
    assert "3." not in out


def test_rendering_no_blocks_is_empty() -> None:
    from revisenlearn.export import render_blocks

    assert render_blocks([]).strip() == ""


# --------------------------------------------------------------------------
# Filename safety
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Hybrid search", "Hybrid search"),
        ("C++/Rust", "C++-Rust"),
        ("a:b*c?d", "a-b-c-d"),
        ("  padded  ", "padded"),
        ("...", "untitled"),
        ("", "untitled"),
        ("CON", "CON-"),                 # reserved on Windows
        ("back\\slash", "back-slash"),
    ],
)
def test_path_components_are_made_safe(raw: str, expected: str) -> None:
    from revisenlearn.export import safe_component

    assert safe_component(raw) == expected


def test_long_names_are_truncated() -> None:
    from revisenlearn.export import safe_component

    assert len(safe_component("x" * 400)) <= 120


# --------------------------------------------------------------------------
# The export itself
# --------------------------------------------------------------------------

def test_export_lays_out_one_folder_per_level(app, client, tmp_path: Path) -> None:
    """Spec §17 — one folder per Subject/Topic/Subtopic, one file per note."""
    tree = _tree(client)
    _note_with(client, tree["subtopic"]["id"],
               [{"block_type": "bullet_list_item", "text": "RRF merges rankings"}])

    dest = _export(client, tmp_path)

    note_dir = dest / "GenAI" / "Retrieval" / "Hybrid search"
    assert note_dir.is_dir()
    files = list(note_dir.glob("*.md"))
    assert len(files) == 1
    assert files[0].name == f"{TODAY}-Hybrid search.md"


def test_front_matter_carries_date_and_resource(app, client, tmp_path: Path) -> None:
    """Spec §17 — "front-matter with date and resource"."""
    tree = _tree(client)
    resource = client.post(
        "/api/resources",
        json={"title": "RAG from scratch", "url": "https://example.com/rag",
              "subtopic_id": tree["subtopic"]["id"]},
    ).json()
    note = client.post(
        "/api/notes/ensure", json={"resource_id": resource["id"]}
    ).json()
    client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [{"id": None, "position": 0,
                          "block_type": "paragraph", "text": "Watched the first half"}]},
    )

    dest = _export(client, tmp_path)
    path = next((dest / "GenAI" / "Retrieval" / "Hybrid search").glob("*.md"))
    text = path.read_text()

    assert text.startswith("---\n")
    assert f'date: "{TODAY}"' in text
    assert 'resource: "RAG from scratch"' in text
    assert 'resource_url: "https://example.com/rag"' in text
    assert 'subject: "GenAI"' in text
    assert 'subtopic: "Hybrid search"' in text
    assert "Watched the first half" in text


def test_front_matter_parses_as_yaml(app, client, tmp_path: Path) -> None:
    """Quoting has to be right, or the insurance policy does not pay out."""
    import yaml

    tree = _tree(client)
    client.patch(
        f"/api/subjects/{tree['subject']['id']}", json={"name": 'Gen"AI: quotes'}
    )
    note = client.post(
        "/api/notes/ensure", json={"subtopic_id": tree["subtopic"]["id"]}
    ).json()
    client.patch(f"/api/notes/{note['id']}", json={"title": 'Title with "quotes" and: colon'})

    dest = _export(client, tmp_path)
    path = next(dest.rglob("*.md"))
    if path.name == "README.md":
        path = next(p for p in dest.rglob("*.md") if p.name != "README.md")

    raw = path.read_text()
    front = raw.split("---\n")[1]
    parsed = yaml.safe_load(front)

    assert parsed["title"] == 'Title with "quotes" and: colon'
    assert parsed["subject"] == 'Gen"AI: quotes'
    assert parsed["date"] == TODAY


def test_notes_without_a_subject_go_to_unfiled(app, client, tmp_path: Path) -> None:
    """Nothing is dropped for being untidy."""
    note = client.post("/api/notes", json={"title": "Loose thought"}).json()
    client.put(
        f"/api/notes/{note['id']}/blocks",
        json={"blocks": [{"id": None, "position": 0,
                          "block_type": "paragraph", "text": "Unfiled but kept"}]},
    )

    dest = _export(client, tmp_path)

    unfiled = list((dest / "_unfiled").glob("*.md"))
    assert len(unfiled) == 1
    assert "Unfiled but kept" in unfiled[0].read_text()


def test_two_notes_with_the_same_title_do_not_overwrite(app, client,
                                                        tmp_path: Path) -> None:
    """§4.1 allows additional notes for the same subtopic and day, and they may
    share a title. Losing one to a filename collision would be the exact
    failure this feature exists to prevent."""
    tree = _tree(client)
    first = client.post(
        "/api/notes/ensure", json={"subtopic_id": tree["subtopic"]["id"]}
    ).json()
    second = client.post(
        "/api/notes",
        json={"subtopic_id": tree["subtopic"]["id"], "title": first["title"]},
    ).json()
    for note, text in ((first, "First body"), (second, "Second body")):
        client.put(
            f"/api/notes/{note['id']}/blocks",
            json={"blocks": [{"id": None, "position": 0,
                              "block_type": "paragraph", "text": text}]},
        )

    dest = _export(client, tmp_path)

    files = sorted((dest / "GenAI" / "Retrieval" / "Hybrid search").glob("*.md"))
    assert len(files) == 2
    bodies = "".join(f.read_text() for f in files)
    assert "First body" in bodies
    assert "Second body" in bodies


def test_soft_deleted_notes_are_not_exported(app, client, tmp_path: Path) -> None:
    tree = _tree(client)
    keep = _note_with(client, tree["subtopic"]["id"],
                      [{"block_type": "paragraph", "text": "Keep me"}])
    drop = client.post(
        "/api/notes",
        json={"subtopic_id": tree["subtopic"]["id"], "title": "Deleted note"},
    ).json()
    client.put(
        f"/api/notes/{drop['id']}/blocks",
        json={"blocks": [{"id": None, "position": 0,
                          "block_type": "paragraph", "text": "Drop me"}]},
    )
    client.delete(f"/api/notes/{drop['id']}")

    dest = _export(client, tmp_path)

    bodies = "".join(p.read_text() for p in dest.rglob("*.md"))
    assert "Keep me" in bodies
    assert "Drop me" not in bodies
    assert keep["id"]


def test_export_reports_its_counts(app, client, tmp_path: Path) -> None:
    tree = _tree(client)
    _note_with(client, tree["subtopic"]["id"],
               [{"block_type": "paragraph", "text": "One"}])
    client.post("/api/notes", json={"title": "Two", "subtopic_id": tree["subtopic"]["id"]})

    dest = tmp_path / "counted"
    result = client.post(
        "/api/export/markdown", json={"destination": str(dest)}
    ).json()

    assert result["note_count"] == 2
    assert result["file_count"] == 2


def test_export_writes_a_self_explaining_readme(app, client, tmp_path: Path) -> None:
    tree = _tree(client)
    _note_with(client, tree["subtopic"]["id"],
               [{"block_type": "paragraph", "text": "Body"}])

    dest = _export(client, tmp_path)
    readme = (dest / "README.md").read_text()

    assert "Revise & Learn" in readme
    assert "One folder per Subject / Topic / Subtopic" in readme
    assert "Nothing here needs the app to read it." in readme


def test_export_of_an_empty_database_still_works(app, client, tmp_path: Path) -> None:
    dest = _export(client, tmp_path, "empty")

    assert dest.is_dir()
    assert (dest / "README.md").exists()
    assert [p.name for p in dest.rglob("*.md")] == ["README.md"]


def test_export_defaults_to_the_data_directory(app, client) -> None:
    """No destination given -> ~/.revisenlearn/exports/export-<timestamp>."""
    result = client.post("/api/export/markdown", json={}).json()

    path = Path(result["path"])
    assert path.is_dir()
    assert path.parent.name == "exports"
    assert path.name.startswith("export-")


def test_a_relative_destination_is_rejected(client) -> None:
    """An ambiguous destination would scatter the user's insurance policy
    wherever the server happened to be running."""
    assert client.post(
        "/api/export/markdown", json={"destination": "somewhere/relative"}
    ).status_code == 400


def test_export_is_readable_without_the_app(app, client, tmp_path: Path) -> None:
    """The whole promise, end to end: plain text, no tooling."""
    tree = _tree(client)
    _note_with(client, tree["subtopic"]["id"], [
        {"block_type": "heading1", "text": "Hybrid search"},
        {"block_type": "bullet_list_item", "text": "BM25 for rare exact terms"},
        {"block_type": "bullet_list_item", "text": "Dense for paraphrase"},
    ])

    dest = _export(client, tmp_path)
    path = next(p for p in dest.rglob("*.md") if p.name != "README.md")
    text = path.read_text(encoding="utf-8")

    body = text.split("---\n", 2)[2]
    assert body.strip() == (
        "# Hybrid search\n\n"
        "- BM25 for rare exact terms\n"
        "- Dense for paraphrase"
    )
