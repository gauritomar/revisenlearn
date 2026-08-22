import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type LessonBrief, type Subject, type TreeKind } from '../lib/api'
import { useOpenLesson } from '../lib/openLesson'
import { useUI } from '../store/ui'

/** Spec §14 — left sidebar: Subjects → Topics → Subtopics, collapsible, state
 *  persisted. Three fixed levels of hierarchy, no arbitrary nesting (§3
 *  **[LOCKED]**), with a Lesson's note hanging off the bottom.
 *
 *  Consolidated addendum §5 makes the interaction Notion's, exactly:
 *  "clicking a page's **chevron** expands children inline without navigating;
 *  clicking the **name** navigates to open that page." Subject, Topic and
 *  Subtopic are organisational, so only their chevrons do anything; a
 *  Lesson's name opens its note (§3). Every row hides a trash icon until it
 *  is hovered, and every row can be dragged onto another to reorder or
 *  reparent it.
 */
export function LeftSidebar() {
  const { data: subjects = [], isLoading } = useQuery({
    queryKey: ['subjects'],
    queryFn: api.subjects,
  })
  const setAddDialog = useUI((s) => s.setAddDialog)

  return (
    <aside
      data-testid="left-sidebar"
      className="flex h-full w-60 shrink-0 flex-col border-r border-line bg-paper"
    >
      <div className="flex h-11 shrink-0 items-center justify-between gap-2 border-b border-line-soft px-3">
        <span className="text-[0.6875rem] font-semibold uppercase tracking-[0.09em] text-muted">
          Subjects
        </span>
        {/* §5 — "a quick-add entry point … fixed at the top of the sidebar".
            It picks its own parent, so nothing has to be expanded first. */}
        <button
          type="button"
          onClick={() => setAddDialog(true)}
          data-testid="sidebar-add"
          aria-label="Add anywhere in the tree"
          title="Add anywhere in the tree  (⌘K → New)"
          className="grid size-6 place-items-center rounded-md border border-line bg-surface text-muted transition hover:border-accent hover:text-accent-deep"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M6 2v8M2 6h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-2">
        {isLoading ? (
          <p className="px-2 py-1 text-[0.8125rem] text-faint">Loading…</p>
        ) : subjects.length === 0 ? (
          <p data-testid="sidebar-empty" className="px-2 py-3 text-[0.8125rem] leading-relaxed text-faint">
            No subjects yet. Press <span className="font-medium text-muted">+</span> to add one.
          </p>
        ) : (
          <ul data-testid="subject-tree" className="space-y-0.5">
            {subjects.map((s, i) => <SubjectRow key={s.id} subject={s} index={i} />)}
          </ul>
        )}
      </div>
    </aside>
  )
}

// --------------------------------------------------------------------------
// Drag and drop
//
// §5 — "**Drag-and-drop reordering** within the sidebar tree, updating each
// item's `position` column." Dropping on a row of the same kind inserts before
// it; dropping on a container row moves the dragged item inside, at the end.
// Both are POST /api/tree/move, which renumbers the siblings densely.
// --------------------------------------------------------------------------

type Dragged = {
  kind: TreeKind
  id: number
  parentId: number | null
  subtopicId: number | null
}

const MIME = 'application/x-rnl-tree'

function read(e: React.DragEvent): Dragged | null {
  try {
    const raw = e.dataTransfer.getData(MIME)
    return raw ? (JSON.parse(raw) as Dragged) : null
  } catch {
    return null
  }
}

/** The parent a dragged item would end up under, or null if the drop makes no
 *  sense (a topic onto a lesson, an item onto itself, …). */
function target(drag: Dragged, onto: Dragged, index: number):
  | { parent_id: number | null; subtopic_id: number | null; position: number }
  | null {
  if (drag.kind === onto.kind && drag.id === onto.id) return null

  // Same kind: reorder, and reparent if the row landed on lives elsewhere.
  if (drag.kind === onto.kind) {
    return { parent_id: onto.parentId, subtopic_id: onto.subtopicId, position: index }
  }
  // A lesson dropped on the subtopic or topic that should hold it.
  if (drag.kind === 'lesson' && onto.kind === 'subtopic') {
    return { parent_id: onto.parentId, subtopic_id: onto.id, position: 9999 }
  }
  if (drag.kind === 'lesson' && onto.kind === 'topic') {
    return { parent_id: onto.id, subtopic_id: null, position: 9999 }
  }
  if (drag.kind === 'subtopic' && onto.kind === 'topic') {
    return { parent_id: onto.id, subtopic_id: null, position: 9999 }
  }
  if (drag.kind === 'topic' && onto.kind === 'subject') {
    return { parent_id: onto.id, subtopic_id: null, position: 9999 }
  }
  return null
}

function useMove() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.moveTreeItem,
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['subjects'] })
      await qc.invalidateQueries({ queryKey: ['roadmap'] })
    },
  })
}

// --------------------------------------------------------------------------
// One row, four levels
// --------------------------------------------------------------------------

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true"
      className={`shrink-0 text-faint transition-transform ${open ? 'rotate-90' : ''}`}
    >
      <path d="m3.5 2 3.5 3-3.5 3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Row({
  kind, id, name, testId, nameTestId, expandable, expanded, onToggle, onOpen,
  onDelete, self, index, active, dot, trailing, className,
}: {
  kind: TreeKind
  id: number
  name: string
  testId: string
  /** Defaults to `{kind}-name-{id}`; lessons key theirs on the name so a test
   *  can click one without first looking up its id. */
  nameTestId?: string
  expandable: boolean
  expanded: boolean
  onToggle: () => void
  /** Only Lessons navigate; for the other three levels the name is inert. */
  onOpen?: () => void
  onDelete: () => Promise<unknown>
  self: Dragged
  index: number
  active?: boolean
  dot?: string | null
  trailing?: React.ReactNode
  className?: string
}) {
  const [confirming, setConfirming] = useState(false)
  const [over, setOver] = useState(false)
  const move = useMove()

  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(MIME, JSON.stringify(self))
        e.dataTransfer.effectAllowed = 'move'
      }}
      onDragOver={(e) => {
        const drag = e.dataTransfer.types.includes(MIME) ? self : null
        if (!drag) return
        e.preventDefault()
        e.dataTransfer.dropEffect = 'move'
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        setOver(false)
        const drag = read(e)
        if (!drag) return
        const where = target(drag, self, index)
        if (!where) return
        e.preventDefault()
        e.stopPropagation()
        move.mutate({ kind: drag.kind, id: drag.id, ...where })
      }}
      data-testid={testId}
      data-kind={kind}
      className={[
        'group flex items-center gap-1 rounded-md pr-1 transition',
        over ? 'ring-1 ring-accent' : '',
        active ? 'bg-accent-wash' : 'hover:bg-sunken',
        className ?? '',
      ].join(' ')}
    >
      {/* The chevron, and only the chevron, expands. */}
      {expandable ? (
        <button
          type="button"
          onClick={onToggle}
          data-testid={`${kind}-chevron-${id}`}
          aria-label={`${expanded ? 'Collapse' : 'Expand'} ${name}`}
          aria-expanded={expanded}
          className="grid size-5 shrink-0 place-items-center rounded transition hover:bg-line-soft"
        >
          <Chevron open={expanded} />
        </button>
      ) : (
        <span className="size-5 shrink-0" aria-hidden="true" />
      )}

      {dot !== undefined && (
        <span
          className="size-2 shrink-0 rounded-full"
          style={{ background: dot ?? 'var(--color-faint)' }}
          aria-hidden="true"
        />
      )}

      {onOpen ? (
        <button
          type="button"
          onClick={onOpen}
          data-testid={nameTestId ?? `${kind}-name-${id}`}
          className="min-w-0 flex-1 truncate py-1.5 text-left text-[0.8125rem] text-ink"
        >
          {name}
        </button>
      ) : (
        // Organisational levels: the name is not a target, so it does not
        // pretend to be one — no pointer cursor, no hover state of its own.
        <span
          data-testid={nameTestId ?? `${kind}-name-${id}`}
          onDoubleClick={onToggle}
          className="min-w-0 flex-1 select-none truncate py-1.5 text-[0.8125rem] text-ink"
        >
          {name}
        </span>
      )}

      {trailing}

      {/* §5 — "hovering any row … reveals a small trash icon", behind one
          confirmation step. */}
      {confirming ? (
        <span className="flex shrink-0 items-center gap-1 text-[0.6875rem]">
          <button
            type="button"
            onClick={async () => { await onDelete(); setConfirming(false) }}
            data-testid={`${kind}-delete-confirm-${id}`}
            className="rounded bg-stale px-1.5 py-0.5 font-medium text-white"
          >
            Delete
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="rounded px-1 py-0.5 text-muted transition hover:text-ink"
          >
            No
          </button>
        </span>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          data-testid={`${kind}-delete-${id}`}
          aria-label={`Delete ${name}`}
          title={`Delete ${name}`}
          className="grid size-5 shrink-0 place-items-center rounded text-faint opacity-0 transition hover:bg-line-soft hover:text-stale focus-visible:opacity-100 group-hover:opacity-100"
        >
          <svg width="11" height="11" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path
              d="M2.5 3.5h7M5 3V2h2v1M4 3.5l.4 6h3.2l.4-6"
              stroke="currentColor" strokeWidth="1.1"
              strokeLinecap="round" strokeLinejoin="round"
            />
          </svg>
        </button>
      )}
    </div>
  )
}

function useDelete(fn: (id: number) => Promise<unknown>, kind: TreeKind) {
  const qc = useQueryClient()
  const clearActive = useUI((s) => s.clearActive)
  return async (id: number) => {
    await fn(id)
    // Close the open note only if the delete could have taken it: a lesson
    // that is the one on screen, or any level above, which cascades.
    const state = useUI.getState()
    if (kind !== 'lesson' || state.activeLessonId === id) clearActive()
    await qc.invalidateQueries({ queryKey: ['subjects'] })
    await qc.invalidateQueries({ queryKey: ['roadmap'] })
  }
}

function SubjectRow({ subject, index }: { subject: Subject; index: number }) {
  const expanded = useUI((s) => s.expandedSubjects.includes(subject.id))
  const toggleSubject = useUI((s) => s.toggleSubject)
  const remove = useDelete(api.deleteSubject, 'subject')

  return (
    <li>
      <Row
        kind="subject"
        id={subject.id}
        name={subject.name}
        testId={`subject-${subject.name}`}
        expandable
        expanded={expanded}
        onToggle={() => toggleSubject(subject.id)}
        onDelete={() => remove(subject.id)}
        self={{ kind: 'subject', id: subject.id, parentId: null, subtopicId: null }}
        index={index}
        dot={subject.colour}
        className="font-medium"
      />

      {expanded && (
        <ul className="ml-3 border-l border-line-soft pl-1.5">
          {subject.topics.length === 0 ? (
            <li className="px-2 py-1 text-[0.75rem] text-faint">No topics</li>
          ) : (
            subject.topics.map((t, i) => (
              <TopicRow key={t.id} topic={t} index={i} />
            ))
          )}
        </ul>
      )}
    </li>
  )
}

function TopicRow({ topic, index }: { topic: Subject['topics'][number]; index: number }) {
  const expanded = useUI((s) => s.expandedTopics.includes(topic.id))
  const toggleTopic = useUI((s) => s.toggleTopic)
  const remove = useDelete(api.deleteTopic, 'topic')
  const hasChildren = topic.subtopics.length > 0 || topic.lessons.length > 0

  return (
    <li>
      <Row
        kind="topic"
        id={topic.id}
        name={topic.name}
        testId={`topic-${topic.name}`}
        expandable={hasChildren}
        expanded={expanded}
        onToggle={() => toggleTopic(topic.id)}
        onDelete={() => remove(topic.id)}
        self={{ kind: 'topic', id: topic.id, parentId: topic.subject_id, subtopicId: null }}
        index={index}
      />

      {expanded && (
        <ul className="ml-3 border-l border-line-soft pl-1.5">
          {topic.subtopics.map((st, i) => (
            <SubtopicRow key={st.id} subtopic={st} index={i} />
          ))}
          {/* Lessons hanging straight off the topic, with no subtopic. */}
          {topic.lessons.map((lesson, i) => (
            <LessonRow key={lesson.id} lesson={lesson} index={i} />
          ))}
          {!hasChildren && (
            <li className="px-2 py-1 text-[0.75rem] text-faint">Empty</li>
          )}
        </ul>
      )}
    </li>
  )
}

function SubtopicRow({ subtopic, index }: {
  subtopic: Subject['topics'][number]['subtopics'][number]
  index: number
}) {
  const expanded = useUI((s) => s.expandedSubtopics.includes(subtopic.id))
  const toggleSubtopic = useUI((s) => s.toggleSubtopic)
  const remove = useDelete(api.deleteSubtopic, 'subtopic')

  return (
    <li>
      <Row
        kind="subtopic"
        id={subtopic.id}
        name={subtopic.name}
        testId={`subtopic-${subtopic.name}`}
        expandable={subtopic.lessons.length > 0}
        expanded={expanded}
        onToggle={() => toggleSubtopic(subtopic.id)}
        onDelete={() => remove(subtopic.id)}
        self={{ kind: 'subtopic', id: subtopic.id, parentId: subtopic.topic_id, subtopicId: null }}
        index={index}
        className="text-ink-soft"
      />

      {expanded && (
        <ul className="ml-3 border-l border-line-soft pl-1.5">
          {subtopic.lessons.map((lesson, i) => (
            <LessonRow key={lesson.id} lesson={lesson} index={i} />
          ))}
        </ul>
      )}
    </li>
  )
}

function LessonRow({ lesson, index }: { lesson: LessonBrief; index: number }) {
  const expanded = useUI((s) => s.expandedLessons.includes(lesson.id))
  const toggleLesson = useUI((s) => s.toggleLesson)
  const active = useUI((s) => s.activeLessonId === lesson.id)
  const openLesson = useOpenLesson()
  const remove = useDelete(api.deleteLesson, 'lesson')

  // Only worth a chevron if there is something to preview behind it.
  const previewable = lesson.checklist_total > 0
  const { data: items = [] } = useQuery({
    queryKey: ['lesson-checklist', lesson.id],
    queryFn: () => api.lessonChecklist(lesson.id),
    enabled: expanded && previewable,
  })

  return (
    <li>
      <Row
        kind="lesson"
        id={lesson.id}
        name={lesson.name}
        testId={`sidebar-lesson-${lesson.name}`}
        nameTestId={`lesson-open-${lesson.name}`}
        expandable={previewable}
        expanded={expanded}
        onToggle={() => toggleLesson(lesson.id)}
        onOpen={() => void openLesson(lesson.id)}
        onDelete={() => remove(lesson.id)}
        self={{
          kind: 'lesson', id: lesson.id,
          parentId: lesson.topic_id, subtopicId: lesson.subtopic_id,
        }}
        index={index}
        active={active}
        trailing={previewable ? (
          <span className="shrink-0 text-[0.625rem] tabular-nums text-faint">
            {lesson.checklist_done}/{lesson.checklist_total}
          </span>
        ) : undefined}
      />

      {/* A preview, not an editor: ticking happens in the note or the right
          panel, both of which write through to the block (§2). */}
      {expanded && previewable && (
        <ul className="ml-8 space-y-0.5 py-0.5">
          {items.map((item) => (
            <li
              key={item.id}
              className={`truncate text-[0.75rem] ${item.checked ? 'text-faint line-through' : 'text-muted'}`}
            >
              {item.checked ? '✓' : '·'} {item.text}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}
