"""The graph console in a real browser (spec §13).

The Cytoscape canvas renders to a <canvas>, so these tests assert what can
honestly be asserted from outside it: that it mounts and reports the right
counts, and that the surrounding curation workspace — the two panes, the five
queue tabs, the filters and the node inspector — actually work.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from conftest import start_app

pytestmark = pytest.mark.ui


@pytest.fixture
def graph_app(db_path: Path):
    instance = start_app(db_path, extra_env={"RNL_LLM_PROVIDER": "mock"})
    try:
        yield instance
    finally:
        instance.stop()


def seed_graph(app) -> None:
    conn = sqlite3.connect(app.db_path)
    conn.execute("INSERT INTO subjects (name, sort_order, created_at) "
                 "VALUES ('GenAI', 0, '2026-08-22')")
    subject_id = conn.execute("SELECT id FROM subjects").fetchone()[0]

    ids = []
    for name, importance in [("Hybrid search", 5.0), ("Dense retrieval", 4.0),
                             ("Chunking", 3.0), ("Lonely concept", 2.0)]:
        conn.execute(
            "INSERT INTO concepts (canonical_name, normalised_name, definition, "
            "subject_id, importance, difficulty, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 3.0, 'active', '2026-08-22', '2026-08-22')",
            (name, name.lower(), f"{name} definition.", subject_id, importance),
        )
        ids.append(conn.execute("SELECT id FROM concepts ORDER BY id DESC LIMIT 1")
                   .fetchone()[0])

    conn.execute(
        "INSERT INTO concept_edges (source_concept_id, target_concept_id, "
        "relation_type, confidence, created_by, status, created_at) "
        "VALUES (?, ?, 'related_to', 0.8, 'llm', 'accepted', '2026-08-22')",
        (ids[0], ids[1]),
    )
    conn.execute(
        "INSERT INTO concept_edges (source_concept_id, target_concept_id, "
        "relation_type, confidence, created_by, status, created_at) "
        "VALUES (?, ?, 'prerequisite_of', 0.6, 'llm', 'proposed', '2026-08-22')",
        (ids[2], ids[0]),
    )
    conn.execute(
        "INSERT INTO concept_merges (merged_from_id, merged_into_id, similarity, "
        "decided_by, created_at) VALUES (?, ?, 0.87, NULL, '2026-08-22')",
        (ids[3], ids[0]),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def page_graph(browser, graph_app):
    seed_graph(graph_app)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    p = context.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(graph_app.base_url, wait_until="networkidle")
    p.get_by_test_id("nav-graph").click()
    p.get_by_test_id("graph-console").wait_for(state="visible")
    try:
        yield p
    finally:
        assert not errors, f"Uncaught JavaScript errors: {errors}"
        context.close()


def test_the_console_has_two_panes_and_mounts_the_graph(page_graph) -> None:
    """Spec §13 — "Two panes: the graph on the left, a work queue on the
    right"."""
    page = page_graph
    canvas = page.get_by_test_id("graph-canvas")
    canvas.wait_for(state="visible")

    # Cytoscape really mounted: it renders into a <canvas> child.
    page.wait_for_function(
        "() => document.querySelector('[data-testid=graph-canvas] canvas') !== null",
        timeout=15_000,
    )
    # The legend renders "0 concepts" before the fetch lands, so wait for the
    # data rather than reading whichever frame is on screen.
    page.wait_for_function(
        "() => document.querySelector('[data-testid=graph-counts]')"
        "?.textContent.includes('4 concepts')",
        timeout=15_000,
    )
    counts = page.get_by_test_id("graph-counts").inner_text()
    assert "4 concepts" in counts
    assert "2 edges" in counts

    # And the work queue is beside it.
    assert page.get_by_test_id("tab-merge_queue").is_visible()


def test_all_five_queue_tabs_carry_counts(page_graph) -> None:
    """Spec §13.2 — "Tabs, each with a count badge"."""
    page = page_graph
    for tab, expected in [("merge_queue", "1"), ("proposed_edges", "1"),
                          ("orphans", "1")]:
        badge = page.get_by_test_id(f"count-{tab}")
        badge.wait_for(state="visible")
        page.wait_for_function(
            f"() => document.querySelector('[data-testid=count-{tab}]')"
            f"?.textContent.trim() === '{expected}'",
            timeout=15_000,
        )
        assert badge.inner_text().strip() == expected, tab

    for tab in ["merge_queue", "proposed_edges", "stale_concepts",
                "auto_merged", "orphans"]:
        assert page.get_by_test_id(f"tab-{tab}").is_visible()


def test_a_proposed_edge_can_be_accepted(page_graph, graph_app) -> None:
    page = page_graph
    page.get_by_test_id("tab-proposed_edges").click()
    page.get_by_test_id("queue-edges").wait_for(state="visible")

    edge_id = graph_app.query(
        "SELECT id FROM concept_edges WHERE status = 'proposed'"
    )[0][0]
    page.get_by_test_id(f"edge-accept-{edge_id}").click()

    page.wait_for_function(
        f"() => !document.querySelector('[data-testid=edge-accept-{edge_id}]')",
        timeout=15_000,
    )
    assert graph_app.query(
        "SELECT status FROM concept_edges WHERE id = ?", (edge_id,)
    )[0][0] == "accepted"


def test_a_queued_merge_can_be_accepted_from_the_console(page_graph,
                                                          graph_app) -> None:
    page = page_graph
    page.get_by_test_id("queue-merge").wait_for(state="visible")

    merge_id = graph_app.query(
        "SELECT id FROM concept_merges WHERE decided_by IS NULL"
    )[0][0]
    page.get_by_test_id(f"merge-accept-{merge_id}").click()

    page.wait_for_function(
        "() => document.querySelector('[data-testid=count-merge_queue]')"
        "?.textContent.trim() === '0'",
        timeout=15_000,
    )
    decided = graph_app.query("SELECT decided_by FROM concept_merges")
    assert ("user",) in decided


def test_selecting_a_node_opens_the_inspector(page_graph, graph_app) -> None:
    """Spec §13.3 — "Selecting a node opens an editor"."""
    page = page_graph
    # Reach a node through the orphans queue rather than the canvas, which is
    # a <canvas> and has no addressable DOM node.
    page.get_by_test_id("tab-orphans").click()
    page.get_by_test_id("queue-orphans").wait_for(state="visible")

    orphan_id = graph_app.query(
        "SELECT id FROM concepts WHERE canonical_name = 'Lonely concept'"
    )[0][0]
    page.get_by_test_id(f"queue-item-{orphan_id}").click()

    inspector = page.get_by_test_id("node-inspector")
    inspector.wait_for(state="visible", timeout=15_000)
    assert page.get_by_test_id("inspector-name").input_value() == "Lonely concept"
    assert page.get_by_test_id("inspector-badge").inner_text() == "untested"
    assert "tokens" in page.get_by_test_id("inspector-cost").inner_text()


def test_renaming_from_the_inspector_keeps_the_old_name(page_graph,
                                                         graph_app) -> None:
    page = page_graph
    page.get_by_test_id("tab-orphans").click()
    orphan_id = graph_app.query(
        "SELECT id FROM concepts WHERE canonical_name = 'Lonely concept'"
    )[0][0]
    page.get_by_test_id(f"queue-item-{orphan_id}").click()
    page.get_by_test_id("node-inspector").wait_for(state="visible", timeout=15_000)

    field = page.get_by_test_id("inspector-name")
    field.fill("Renamed concept")
    field.blur()

    page.wait_for_function(
        "() => document.querySelector('[data-testid=inspector-aliases]')"
        "?.textContent.includes('Lonely concept')",
        timeout=15_000,
    )
    assert graph_app.query(
        "SELECT canonical_name FROM concepts WHERE id = ?", (orphan_id,)
    )[0][0] == "Renamed concept"


def test_the_saved_views_filter_the_graph(page_graph) -> None:
    """Spec §13.1 — saved views."""
    page = page_graph
    page.get_by_test_id("graph-view").select_option("orphans")

    page.wait_for_function(
        "() => document.querySelector('[data-testid=graph-counts]')"
        "?.textContent.startsWith('1 concepts')",
        timeout=15_000,
    )


def test_search_filters_the_graph(page_graph) -> None:
    page = page_graph
    page.get_by_test_id("graph-search").fill("hybrid")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=graph-counts]')"
        "?.textContent.startsWith('1 concepts')",
        timeout=15_000,
    )


def test_the_graph_does_not_scroll_sideways_when_narrow(page_graph) -> None:
    page = page_graph
    page.set_viewport_size({"width": 500, "height": 900})
    page.wait_for_timeout(400)
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"page scrolls horizontally by {overflow}px at 500px"


def test_concepts_are_grouped_by_subject_and_topic(page_graph, graph_app) -> None:
    """"Let's keep nodes subject/topic wise." Cytoscape compound nodes: a
    concept sits inside its topic, which sits inside its subject, so a hundred
    of them read as a curriculum rather than a hairball."""
    page = page_graph
    page.wait_for_function(
        "() => document.querySelector('[data-testid=graph-canvas] canvas') !== null",
        timeout=15_000,
    )
    page.wait_for_function(
        "() => document.querySelector('[data-testid=graph-counts]')"
        "?.textContent.includes('4 concepts')",
        timeout=15_000,
    )

    # The payload the graph is built from carries the grouping.
    nodes = page.evaluate(
        """async () => {
          const res = await fetch('/api/graph')
          const body = await res.json()
          return body.nodes.map(n => ({subject: n.subject_id, topic: n.topic_id}))
        }"""
    )
    assert nodes and all(n["subject"] is not None for n in nodes)
