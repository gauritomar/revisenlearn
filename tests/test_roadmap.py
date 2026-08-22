"""Lessons, Items, Todos and the progress rollup (addendum §1–§6).

The rollup is `[LOCKED]` and is pure arithmetic, so it is tested exhaustively
against the addendum's own pseudocode. §0.1's structural claim — that checking
a box never creates a concept or touches FSRS — is tested directly.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlmodel import select

from revisenlearn import roadmap
from revisenlearn.checklist import reconcile_note
from revisenlearn.hashing import content_hash
from revisenlearn.models import (
    ChecklistItem,
    Concept,
    Lesson,
    Note,
    NoteBlock,
    ReviewItem,
    ReviewLog,
    Subject,
    Subtopic,
    Todo,
    Topic,
)


def _tree(session) -> dict:
    subject = Subject(name="GenAI")
    session.add(subject)
    session.flush()
    topic = Topic(subject_id=subject.id, name="Retrieval")
    session.add(topic)
    session.flush()
    subtopic = Subtopic(topic_id=topic.id, name="Hybrid search")
    session.add(subtopic)
    session.flush()
    return {"subject": subject, "topic": topic, "subtopic": subtopic}


def _lesson(session, tree, name="Window functions", status="not_started",
            subtopic=True) -> Lesson:
    lesson = Lesson(
        topic_id=tree["topic"].id,
        subtopic_id=tree["subtopic"].id if subtopic else None,
        name=name, status=status,
    )
    session.add(lesson)
    session.flush()
    return lesson


def _items(session, lesson, done: list[bool]) -> list[ChecklistItem]:
    """Write checklist lines into the lesson's note.

    The consolidated addendum §2 made `checklist_items` a projection of note
    blocks, so there is no way to author one directly any more — and these
    tests go through the same path the editor does.
    """
    note = session.exec(
        select(Note).where(Note.lesson_id == lesson.id,
                           Note.deleted_at.is_(None))
    ).first()
    if note is None:
        note = Note(title=lesson.name, study_date=dt.date(2026, 8, 22),
                    lesson_id=lesson.id, topic_id=lesson.topic_id,
                    subtopic_id=lesson.subtopic_id)
        session.add(note)
        session.flush()

    for index, is_done in enumerate(done):
        text = f"- [{'x' if is_done else ' '}] Item {index}"
        session.add(NoteBlock(
            note_id=note.id, position=index, block_type="checklist_item",
            text=text, checked=is_done, content_hash=content_hash(text),
        ))
    session.flush()
    reconcile_note(session, note.id)
    session.flush()
    return roadmap.live_items(session, lesson.id)


# --------------------------------------------------------------------------
# §4 Progress rollup **[LOCKED]**
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status,expected",
    [("not_started", 0.0), ("in_progress", 50.0), ("done", 100.0)],
)
def test_a_lesson_with_no_items_uses_its_status(session, status, expected) -> None:
    tree = _tree(session)
    lesson = _lesson(session, tree, status=status)
    assert roadmap.lesson_pct(session, lesson) == expected


def test_a_lesson_with_items_uses_the_item_ratio(session) -> None:
    """"A Lesson with no Items is still a valid, trackable unit" — but once it
    has them, they govern."""
    tree = _tree(session)
    lesson = _lesson(session, tree, status="not_started")
    _items(session, lesson, [True, True, False, False])

    # Items win over the status, which still says not_started.
    assert roadmap.lesson_pct(session, lesson) == 50.0


def test_subtopic_percent_is_the_mean_of_its_lessons(session) -> None:
    tree = _tree(session)
    _lesson(session, tree, "A", status="done")            # 100
    _lesson(session, tree, "B", status="not_started")     # 0
    _lesson(session, tree, "C", status="in_progress")     # 50

    assert roadmap.subtopic_pct(session, tree["subtopic"].id) == pytest.approx(50.0)


def test_a_subtopic_with_no_lessons_is_none_not_zero(session) -> None:
    """Addendum §4 — "an empty subject shouldn't look '0% learned'"."""
    tree = _tree(session)
    assert roadmap.subtopic_pct(session, tree["subtopic"].id) is None
    assert roadmap.topic_pct(session, tree["topic"].id) is None
    assert roadmap.subject_pct(session, tree["subject"].id) is None


def test_topic_percent_treats_direct_lessons_as_peers(session) -> None:
    """Addendum §4 — "combine subtopics' rollups AND any lessons attached
    directly to the topic … as peers in the same average"."""
    tree = _tree(session)
    # Subtopic rolls up to 100.
    _lesson(session, tree, "In subtopic", status="done")
    # A lesson straight on the topic, at 0.
    _lesson(session, tree, "Direct", status="not_started", subtopic=False)

    # Peers: mean(100, 0) = 50, not a subtopic-weighted figure.
    assert roadmap.topic_pct(session, tree["topic"].id) == pytest.approx(50.0)


def test_a_subtopic_with_no_lessons_is_excluded_from_the_topic_mean(session) -> None:
    tree = _tree(session)
    empty = Subtopic(topic_id=tree["topic"].id, name="Empty")
    session.add(empty)
    session.flush()
    _lesson(session, tree, "Only one", status="done")

    # The empty subtopic does not drag the average to 50.
    assert roadmap.topic_pct(session, tree["topic"].id) == pytest.approx(100.0)


def test_subject_percent_is_the_mean_of_its_topics(session) -> None:
    tree = _tree(session)
    _lesson(session, tree, "Done", status="done")

    other = Topic(subject_id=tree["subject"].id, name="Evaluation")
    session.add(other)
    session.flush()
    session.add(Lesson(topic_id=other.id, name="Nothing yet",
                       status="not_started"))
    session.flush()

    assert roadmap.subject_pct(session, tree["subject"].id) == pytest.approx(50.0)


def test_the_rollup_is_a_simple_mean_not_lesson_weighted(session) -> None:
    """Addendum §4 — "Simple mean of children, not lesson-count-weighted"."""
    tree = _tree(session)
    # One subtopic with three finished lessons.
    for name in ("A", "B", "C"):
        _lesson(session, tree, name, status="done")
    # Another with a single unstarted one.
    other = Subtopic(topic_id=tree["topic"].id, name="Second")
    session.add(other)
    session.flush()
    session.add(Lesson(topic_id=tree["topic"].id, subtopic_id=other.id,
                       name="Alone", status="not_started"))
    session.flush()

    # Weighted by lessons this would be 75%; as a mean of children it is 50%.
    assert roadmap.topic_pct(session, tree["topic"].id) == pytest.approx(50.0)


def test_deleted_lessons_and_items_leave_the_rollup(session) -> None:
    tree = _tree(session)
    done = _lesson(session, tree, "Done", status="done")
    gone = _lesson(session, tree, "Gone", status="not_started")
    gone.deleted_at = dt.datetime.now(dt.timezone.utc)
    session.add(gone)
    session.flush()

    assert roadmap.subtopic_pct(session, tree["subtopic"].id) == 100.0
    assert done.id


# --------------------------------------------------------------------------
# §4 Status coupling
# --------------------------------------------------------------------------

def test_finishing_every_item_flips_the_lesson_to_done(session) -> None:
    """"Marking every Item under a Lesson done auto-flips the Lesson's status
    to `done`.\""""
    tree = _tree(session)
    lesson = _lesson(session, tree)
    items = _items(session, lesson, [False, False])

    roadmap.set_item_done(session, items[0], True)
    session.refresh(lesson)
    assert lesson.status == "not_started"

    roadmap.set_item_done(session, items[1], True)
    session.refresh(lesson)
    assert lesson.status == "done"


def test_a_lesson_can_be_marked_done_with_items_still_open(session) -> None:
    """"The user can mark a Lesson done with items still open (e.g. 'I get this
    well enough, skip the rest')".

    The status is not purely derived, so nothing drags it back.
    """
    tree = _tree(session)
    lesson = _lesson(session, tree)
    items = _items(session, lesson, [False, False])

    lesson.status = "done"
    session.add(lesson)
    session.flush()

    # Ticking one item must not undo that deliberate choice.
    roadmap.set_item_done(session, items[0], True)
    session.refresh(lesson)
    assert lesson.status == "done"

    # The percentage still tells the truth about the boxes.
    assert roadmap.lesson_pct(session, lesson) == 50.0


def test_unticking_an_item_does_not_reopen_a_finished_lesson(session) -> None:
    tree = _tree(session)
    lesson = _lesson(session, tree)
    items = _items(session, lesson, [True])
    roadmap.set_item_done(session, items[0], True)
    session.refresh(lesson)
    assert lesson.status == "done"

    roadmap.set_item_done(session, items[0], False)
    session.refresh(lesson)
    assert lesson.status == "done"


# --------------------------------------------------------------------------
# §0.1 The structural claim
# --------------------------------------------------------------------------

def test_checking_a_box_never_creates_a_concept_or_touches_fsrs(session) -> None:
    """Addendum §0.1 — "checking a box should never create a concept or touch
    FSRS. Concept extraction and revision only happen when the user
    deliberately writes a note. This was already implicitly true; it's now made
    structural.\""""
    tree = _tree(session)
    lesson = _lesson(session, tree)
    items = _items(session, lesson, [False, False, False])

    concept = Concept(canonical_name="Existing", normalised_name="existing",
                      subject_id=tree["subject"].id)
    session.add(concept)
    session.flush()
    review = ReviewItem(concept_id=concept.id, dimension="explain")
    session.add(review)
    session.flush()
    before = (review.due_at, review.reps, review.lapses, review.fsrs_stability)

    for item in items:
        roadmap.set_item_done(session, item, True)
    todo = Todo(title="Redo resume")
    session.add(todo)
    session.flush()
    todo.done = True
    session.add(todo)
    session.flush()

    # One concept, the pre-existing one. Nothing was extracted.
    assert len(session.exec(select(Concept)).all()) == 1
    session.refresh(review)
    assert (review.due_at, review.reps, review.lapses,
            review.fsrs_stability) == before
    assert session.exec(select(ReviewLog)).all() == []


# --------------------------------------------------------------------------
# §6 Roadmap
# --------------------------------------------------------------------------

def test_the_roadmap_returns_the_whole_tree_with_percentages(session) -> None:
    tree = _tree(session)
    lesson = _lesson(session, tree, "Window functions", status="in_progress")
    _items(session, lesson, [True, False])

    data = roadmap.build_roadmap(session)

    subject = data["subjects"][0]
    assert subject["name"] == "GenAI"
    assert subject["pct"] == 50.0
    topic = subject["topics"][0]
    assert topic["pct"] == 50.0
    subtopic_node = topic["subtopics"][0]
    assert subtopic_node["pct"] == 50.0
    lesson_node = subtopic_node["lessons"][0]
    assert lesson_node["name"] == "Window functions"
    assert lesson_node["pct"] == 50.0
    assert len(lesson_node["items"]) == 2


def test_the_roadmap_shows_completed_work_too(session) -> None:
    """Addendum §6 — "Always shows everything, completed included — no
    hide-completed toggle here"."""
    tree = _tree(session)
    _lesson(session, tree, "Finished", status="done")

    data = roadmap.build_roadmap(session)
    names = [
        l["name"]
        for s in data["subjects"] for t in s["topics"]
        for st in t["subtopics"] for l in st["lessons"]
    ]
    assert "Finished" in names
    assert "hide_completed" not in data


def test_the_roadmap_carries_no_mastery_vocabulary(session) -> None:
    """Addendum §5 **[LOCKED]** — this layer "must not share a visual language"
    with FSRS mastery badges. A bare percentage is returned; there is nothing
    here for a UI to traffic-light."""
    import json

    tree = _tree(session)
    _lesson(session, tree, "Done", status="done")

    blob = json.dumps(roadmap.build_roadmap(session)).lower()
    for word in ["mastered", "fading", "learning", "untested", "badge",
                 "mastery", "freshness", "retrievability"]:
        assert word not in blob


# --------------------------------------------------------------------------
# §6 Todos board
# --------------------------------------------------------------------------

def test_the_board_combines_todos_lessons_and_items(session) -> None:
    tree = _tree(session)
    lesson = _lesson(session, tree, "Window functions")
    _items(session, lesson, [False])
    session.add(Todo(title="Redo resume"))
    session.flush()

    board = roadmap.todo_board(session)

    kinds = {e["kind"] for e in board["entries"]}
    assert kinds == {"todo", "lesson", "lesson_item"}
    titles = {e["title"] for e in board["entries"]}
    assert {"Redo resume", "Window functions", "Item 0"} <= titles


def test_the_board_hides_completed_by_default(session) -> None:
    """"This is the view with the hide-completed toggle, default on — its job
    is 'what's left'.\""""
    tree = _tree(session)
    _lesson(session, tree, "Finished", status="done")
    open_todo = Todo(title="Still open")
    done_todo = Todo(title="Already done", done=True)
    session.add_all([open_todo, done_todo])
    session.flush()

    hidden = roadmap.todo_board(session)
    assert {e["title"] for e in hidden["entries"]} == {"Still open"}
    assert hidden["hide_completed"] is True

    shown = roadmap.todo_board(session, hide_completed=False)
    assert {"Finished", "Already done", "Still open"} <= {
        e["title"] for e in shown["entries"]
    }


def test_the_board_sorts_nearest_due_date_first(session) -> None:
    session.add_all([
        Todo(title="No date"),
        Todo(title="Later", due_date=dt.date(2026, 12, 1)),
        Todo(title="Sooner", due_date=dt.date(2026, 9, 1)),
    ])
    session.flush()

    titles = [e["title"] for e in roadmap.todo_board(session)["entries"]]
    assert titles == ["Sooner", "Later", "No date"]


def test_the_board_filters(session) -> None:
    tree = _tree(session)
    other = Subject(name="Systems")
    session.add(other)
    session.flush()
    session.add_all([
        Todo(title="In GenAI", subject_id=tree["subject"].id),
        Todo(title="In Systems", subject_id=other.id),
        Todo(title="Dated", due_date=dt.date(2026, 9, 1)),
    ])
    session.flush()

    by_subject = roadmap.todo_board(session, subject_id=tree["subject"].id)
    assert {e["title"] for e in by_subject["entries"]} == {"In GenAI"}

    dated = roadmap.todo_board(session, has_due_date=True)
    assert {e["title"] for e in dated["entries"]} == {"Dated"}


def test_the_dashboard_panel_is_short(session) -> None:
    """Addendum §6 — "a short Todos panel (5–7 items … nearest due date
    first)"."""
    for i in range(20):
        session.add(Todo(title=f"Todo {i}"))
    session.flush()

    assert len(roadmap.dashboard_todos(session)) == 7
