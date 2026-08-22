# Addendum: Lessons, Items, Todos & Flexible Linking

**Applies to:** `revise-and-learn-v1-spec.md`
**Supersedes:** `revise-and-learn-v1-spec-ADDENDUM-resource-items.md` — that
addendum's `resource_items` table is discarded. If it was already built,
migrate away from it per §7 below.
**Build as:** its own phase, referred to here as **Phase 2b**, done
alongside or immediately after Phase 2. It does not require restarting
anything already built in Phase 2 — notes and resources keep working exactly
as they do; this adds a parallel tracking layer and loosens some ownership
rules.

---

## 0. What changed and why

Two things came out of reviewing the user's actual study habits:

1. **Practice tracking and concept learning are different activities and
   should not be forced through the same pipeline.** CodeChef grinding,
   LeetCode reps, and course checklists are pure "did I do it" tracking —
   checking a box should never create a concept or touch FSRS. Concept
   extraction and revision only happen when the user deliberately writes a
   note. This was already implicitly true; it's now made structural.

2. **Notes and Resources should link flexibly, not be owned by a single
   parent.** A note might reference two resources; a resource might be
   useful across several lessons; a note might exist with no resource at
   all. The original spec's single `resource_id` FK on `notes` was too
   rigid for how the user actually thinks about her material.

---

## 1. New hierarchy level: Lesson

```
Subject → Topic → Subtopic (optional) → Lesson → Item(s) (optional)
```

A **Lesson** is a coherent chunk of study — "Window Functions," "Transformer
self-attention," "Two Pointers" — the level at which the user tracks
progress. It requires a Topic but not a Subtopic (mirrors how Notes already
work — Subtopic is optional everywhere in the spec).

```sql
lessons(id, topic_id, subtopic_id, name, position, status,
        created_at, updated_at, deleted_at)
        -- status: not_started | in_progress | done
        -- status is directly settable by the user, not purely derived —
        -- see §4 for the relationship to item completion
```

An **Item** is an optional checkbox sub-step under a Lesson — the granular
"Build byte-pair encoder," "Broadcasting," "Case Study: Library Management
System" level. Deliberately simple: a checkbox and nothing else.

```sql
lesson_items(id, lesson_id, title, position, done, completed_at,
             created_at, updated_at, deleted_at)
```

No third level. A Lesson with no Items is still a valid, trackable unit —
its own status is enough for something atomic like "watch this video."

---

## 2. Flexible linking

Resources keep a primary home (`subject_id`/`topic_id`/`subtopic_id`, as in
the original spec §6) so they're still browsable in the sidebar as "things
I've saved." Notes keep their primary home too, for the same reason and to
preserve calendar/dashboard behaviour already built in Phase 2.

On top of that, add many-to-many join tables so the same note or resource
can attach to more than one place:

```sql
note_lesson_links(id, note_id, lesson_id, created_at)
note_resource_links(id, note_id, resource_id, created_at)
lesson_resource_links(id, lesson_id, resource_id, created_at)
```

`notes.resource_id` (from the original spec) stays as-is and means
"the resource I was primarily working from when I wrote this" — a
convenience default, not the only link. `note_resource_links` covers
everything beyond that one.

**Behavioural rule, unchanged from before:** creating or opening a Resource
never requires a note. Some resources will have linked notes, most won't,
and that's fine — nothing in the UI should prompt "write a note for this."

---

## 3. Standalone Todos

Not tied to a Lesson, Resource, or Note. Covers anything from "redo resume"
to "read this paper" — general life-adjacent todos the user wants in the
same place as study tracking, since this app is meant to be the one stop
for studying-related everything.

```sql
todos(id, title, subject_id, topic_id, due_date, done, completed_at,
      position, created_at, updated_at, deleted_at)
      -- subject_id and topic_id are both nullable — a todo can be
      -- untagged, or loosely tagged to a subject/topic without being
      -- a Lesson or Item
```

Just a checkbox, a title, and an optional due date. No priority field, no
status enum beyond done/not done — matches the minimal-friction answer given
for Items.

---

## 4. Progress rollup **[LOCKED]**

Computed on read; no caching needed at this data scale.

```python
def lesson_pct(lesson):
    items = lesson.items
    if items:
        return 100 * sum(1 for i in items if i.done) / len(items)
    return {"not_started": 0, "in_progress": 50, "done": 100}[lesson.status]

def subtopic_pct(subtopic):
    lessons = subtopic.lessons
    return mean(lesson_pct(l) for l in lessons) if lessons else None

def topic_pct(topic):
    # combine subtopics' rollups AND any lessons attached directly to
    # the topic (subtopic_id is null) as peers in the same average
    children_pcts = [subtopic_pct(s) for s in topic.subtopics if s.lessons]
    direct_lesson_pcts = [lesson_pct(l) for l in topic.lessons_without_subtopic]
    all_pcts = children_pcts + direct_lesson_pcts
    return mean(all_pcts) if all_pcts else None

def subject_pct(subject):
    topic_pcts = [topic_pct(t) for t in subject.topics if topic_pct(t) is not None]
    return mean(topic_pcts) if topic_pcts else None
```

Simple mean of children, not lesson-count-weighted — good enough for this
use case and much simpler to reason about. Percentages with no data
underneath (`None`) render as an empty/grey state, not `0%` — an empty
subject shouldn't look "0% learned."

**Marking every Item under a Lesson done auto-flips the Lesson's status to
`done`.** The Lesson's status checkbox is still directly clickable and
overridable at any time — it isn't purely derived, so the user can mark a
Lesson done with items still open (e.g. "I get this well enough, skip the
rest") or reopen a completed Lesson.

---

## 5. Visual distinction from FSRS mastery **[LOCKED — important]**

This progress layer and the FSRS mastery badges from §10.5 of the main spec
**must not share a visual language.** A green "100%" here means "I checked
every box." A green "Mastered" badge on the concept side means "I can
recall and explain this reliably, recently." Conflating them would quietly
teach the user that finishing a checklist is the same as knowing the
material — exactly the wrong lesson for an app built around retrieval
practice.

Use a plain percentage bar (grey track, single accent fill, no traffic-light
colour semantics) for Lesson/Subtopic/Topic/Subject progress. Reserve the
green/amber/blue/grey mastery states strictly for concept dimensions.

---

## 6. Three views

**Roadmap view** (new top-level nav item, alongside Dashboard/Notes/
Practice/Revision/Graph): the full tree, Subject → Topic → Subtopic →
Lesson → Items, with percentage bars at every level. Always shows
everything, completed included — no hide-completed toggle here; seeing the
whole shape of a curriculum, finished parts included, is the point of this
view.

**Todos view** (new top-level nav item): a flat, filterable, cross-cutting
list combining standalone Todos and any open Lesson/Item across every
subject. Filters: subject, topic, has-due-date. **This is the view with the
hide-completed toggle**, default on — its job is "what's left," unlike
Roadmap view.

**Dashboard**: add a short **Todos** panel (5–7 items, standalone todos plus
any due-dated items, nearest due date first) to the existing Today /
Continue learning / Calendar / Progress sections from the main spec §14.
Link out to the full Todos view.

---

## 7. In-app tree builder **[LOCKED]**

No paste-import for this layer — the user wants to build these natively.
(Note: this replaces the checklist paste-import feature from the earlier,
now-superseded addendum. Drop that feature if it was built.)

On a Subtopic (or Topic, for Lessons without a Subtopic): an inline
"+ Add lesson" row. Typing text and pressing **Enter** creates the Lesson
and immediately opens a fresh "+ Add lesson" row below it, so multiple
lessons can be added in a fast burst without re-clicking anything.

Pressing **Tab** while adding a Lesson switches into "add item" mode nested
under the lesson just created (or the one currently focused): typing and
pressing Enter adds Items one after another the same way. **Shift+Tab** or
**Escape** pops back out to Lesson-adding at the parent level.

This is the entire authoring flow — no separate "create" dialog, no modal.
Existing Lessons/Items are edited inline on click; reordering is drag-handle
based, updating `position`.

---

## 8. Extraction context (minor, non-structural)

When a Note is linked to one or more Lessons via `note_lesson_links`, pass
the linked Lesson name(s) into the concept-extraction prompt's context
alongside the existing Subject/Topic/Subtopic path (§11.1 of the main
spec). This is additive context only — extraction still works exactly as
specced when no Lesson link exists.

---

## 9. Migration note for Claude Code

If `resource_items` (from the earlier, now-superseded addendum) was already
created:

1. Write a migration dropping `resource_items` and any endpoints/UI built
   for it (`/api/resources/{id}/items*`, the paste-import box on the
   Resource detail page).
2. If any real data exists in `resource_items` already (unlikely this early,
   but check), do not silently discard it — write a one-off script that
   converts each row into a `lessons` row (with a matching `lesson_items`
   row if the resource_item had sub-structure) under the resource's existing
   subject/topic/subtopic, and log what it converted.
3. Proceed with this addendum's schema as the standing design from here on.

---

## 10. Schema diff summary

**New tables:** `lessons`, `lesson_items`, `todos`, `note_lesson_links`,
`note_resource_links`, `lesson_resource_links`

**Removed (if present):** `resource_items` and its endpoints/UI

**Unchanged:** everything else in §6 of the main spec, including
`notes.resource_id` as a nullable convenience default

**New endpoints:**
```
GET/POST/PATCH/DELETE  /api/lessons
GET/POST/PATCH/DELETE  /api/lessons/{id}/items
GET/POST/PATCH/DELETE  /api/todos
POST/DELETE            /api/notes/{id}/links/lessons/{lesson_id}
POST/DELETE            /api/notes/{id}/links/resources/{resource_id}
POST/DELETE            /api/lessons/{id}/links/resources/{resource_id}
GET                     /api/roadmap                 (full tree with rollups)
GET                     /api/todos/board              (cross-cutting, filtered)
```

**Build order:** Phase 2b, alongside or immediately following Phase 2. Does
not block or get blocked by Phase 3 (backup) — sequence backup after this
if it isn't already in place, since this phase adds real data worth
protecting.
