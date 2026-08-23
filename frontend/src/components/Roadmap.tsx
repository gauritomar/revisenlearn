import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type RoadmapLesson, type RoadmapSubject, type TreeKind } from '../lib/api'
import { useRefreshEverything } from '../lib/refresh'
import { useUI } from '../store/ui'

/** Lesson status, in the user's words: "click on its done to do button and it
 *  will be highlighted in green and in-progress should be yellow, red if i
 *  need to return to it."
 *
 *  `revisit` is the red one, and it is a different thing from never having
 *  started: it means the work was done and did not stick. Clicking cycles
 *  through all four, so one control covers the whole state. */
const STATUS_CYCLE: Record<string, string> = {
  not_started: 'in_progress',
  in_progress: 'done',
  done: 'revisit',
  revisit: 'not_started',
}

const STATUS_STYLE: Record<string, { box: string; row: string; label: string }> = {
  not_started: {
    box: 'border-line text-transparent hover:border-faint',
    row: '',
    label: 'not started',
  },
  in_progress: {
    box: 'border-amber-500 bg-amber-100 text-amber-700',
    row: 'bg-amber-50/60',
    label: 'in progress',
  },
  done: {
    box: 'border-emerald-600 bg-emerald-600 text-white',
    row: 'bg-emerald-50/60',
    label: 'done',
  },
  revisit: {
    box: 'border-rose-500 bg-rose-100 text-rose-700',
    row: 'bg-rose-50/60',
    label: 'come back to this',
  },
}

const STATUS_MARK: Record<string, string> = {
  not_started: '·', in_progress: '–', done: '✓', revisit: '!',
}

/** Roadmap — the whole curriculum, and the way into every note.
 *
 *  "Let's keep just roadmap as a way to add notes … this is now the
 *  centralised way to access notes." So this screen owns three jobs that used
 *  to be spread around: seeing the shape of everything, adding anything
 *  anywhere, and deleting it. Clicking any name opens that page.
 *
 *  Addendum §6: "Always shows everything, completed included — no
 *  hide-completed toggle here; seeing the whole shape of a curriculum,
 *  finished parts included, is the point of this view."
 *
 *  Addendum §5 **[LOCKED]**: these bars must not share a visual language with
 *  FSRS mastery badges. A grey track with a single accent fill, no
 *  traffic-light colour, no badge words. A green 100% here would quietly teach
 *  that finishing a checklist is the same as knowing the material.
 */
export function Roadmap() {
  const { data, isLoading } = useQuery({ queryKey: ['roadmap'], queryFn: api.roadmap })
  const refresh = useRefreshEverything()
  const [addingSubject, setAddingSubject] = useState(false)

  const addSubject = useMutation({
    mutationFn: (name: string) => api.createSubject(name),
    onSuccess: refresh,
  })

  return (
    <div data-testid="roadmap" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-xl font-semibold tracking-tight text-ink">Roadmap</h2>
        <button
          type="button"
          onClick={() => setAddingSubject(true)}
          data-testid="roadmap-add-subject"
          className="rounded-md border border-line bg-surface px-2.5 py-1 text-[0.75rem] text-ink transition hover:border-accent hover:text-accent-deep"
        >
          + Subject
        </button>
      </div>
      <p className="mt-1 text-[0.875rem] leading-relaxed text-muted">
        Everything you are working through. Click any name to open its page and
        write. Ticking a box tracks progress through material, not what you
        know — those two are deliberately separate.
      </p>

      {addingSubject && (
        <NameInput
          placeholder="Subject name"
          testid="roadmap-new-subject"
          onCancel={() => setAddingSubject(false)}
          onSubmit={(name) => addSubject.mutate(name)}
        />
      )}

      {isLoading ? (
        <p className="mt-5 text-[0.8125rem] text-faint">Loading…</p>
      ) : (data?.subjects.length ?? 0) === 0 && !addingSubject ? (
        <p data-testid="roadmap-empty" className="mt-5 rounded-lg border border-dashed border-line bg-surface p-8 text-center text-[0.875rem] text-faint">
          Nothing here yet. Press <span className="text-muted">+ Subject</span> to start.
        </p>
      ) : (
        <div className="mt-5 space-y-4">
          {data?.subjects.map((subject, i) => (
            <SubjectBlock key={subject.id} subject={subject} index={i} />
          ))}
        </div>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------
// Shared row furniture
// --------------------------------------------------------------------------

/** An inline name field. Enter adds and stays open, Escape cancels,
 *  blur-while-empty cancels.
 *
 *  Staying open is addendum §7 **[LOCKED]**: "Typing text and pressing Enter
 *  creates the Lesson and immediately opens a fresh '+ Add lesson' row below
 *  it, so multiple lessons can be added in a fast burst without re-clicking
 *  anything." No dialog: adding a subject should cost one keystroke more than
 *  thinking of the name. */
function NameInput({ placeholder, testid, onSubmit, onCancel, indent }: {
  placeholder: string
  testid: string
  onSubmit: (name: string) => void
  onCancel: () => void
  indent?: string
}) {
  return (
    <form
      className={`mt-1 ${indent ?? ''}`}
      onSubmit={(e) => {
        e.preventDefault()
        const input = e.currentTarget.elements.namedItem('name') as HTMLInputElement
        const name = input.value.trim()
        if (name) onSubmit(name)
        input.value = ''
      }}
    >
      <input
        name="name"
        autoFocus
        data-testid={testid}
        placeholder={placeholder}
        onKeyDown={(e) => { if (e.key === 'Escape') onCancel() }}
        onBlur={(e) => { if (!e.currentTarget.value.trim()) onCancel() }}
        className="w-full rounded-md border border-accent bg-surface px-2 py-1 text-[0.8125rem] text-ink outline-none"
      />
    </form>
  )
}

/** Delete, behind one confirmation. The Roadmap is the only place this lives:
 *  a trash icon in the sidebar is too easy to hit while navigating. */
function DeleteButton({ kind, id, name, onDeleted }: {
  kind: TreeKind
  id: number
  name: string
  onDeleted: () => void | Promise<void>
}) {
  const [confirming, setConfirming] = useState(false)
  const clearActive = useUI((s) => s.clearActive)

  const remove = useMutation({
    mutationFn: () => ({
      subject: api.deleteSubject, topic: api.deleteTopic,
      subtopic: api.deleteSubtopic, lesson: api.deleteLesson,
    }[kind])(id),
    onSuccess: async () => {
      setConfirming(false)
      // Whatever was open may have just been deleted along with its parent.
      clearActive()
      await onDeleted()
    },
  })

  if (confirming) {
    return (
      <span className="flex shrink-0 items-center gap-1 text-[0.6875rem]">
        <span className="text-muted">Delete {kind}?</span>
        <button
          type="button"
          onClick={() => remove.mutate()}
          disabled={remove.isPending}
          data-testid={`delete-confirm-${kind}-${id}`}
          className="rounded bg-stale px-1.5 py-0.5 font-medium text-white disabled:opacity-50"
        >
          Yes
        </button>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className="rounded px-1 py-0.5 text-muted transition hover:text-ink"
        >
          No
        </button>
      </span>
    )
  }

  return (
    <button
      type="button"
      onClick={() => setConfirming(true)}
      data-testid={`delete-${kind}-${id}`}
      aria-label={`Delete ${name}`}
      title={`Delete ${name}`}
      className="grid size-5 shrink-0 place-items-center rounded text-faint opacity-0 transition hover:bg-sunken hover:text-stale focus-visible:opacity-100 group-hover:opacity-100"
    >
      <svg width="11" height="11" viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path d="M2.5 3.5h7M5 3V2h2v1M4 3.5l.4 6h3.2l.4-6"
              stroke="currentColor" strokeWidth="1.1"
              strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  )
}

function AddButton({ label, onClick, testid }: {
  label: string
  onClick: () => void
  testid: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testid}
      className="shrink-0 rounded px-1.5 py-0.5 text-[0.6875rem] text-faint opacity-0 transition hover:bg-sunken hover:text-accent-deep focus-visible:opacity-100 group-hover:opacity-100"
    >
      + {label}
    </button>
  )
}

/** Addendum §5 — "a plain percentage bar (grey track, single accent fill, no
 *  traffic-light colour semantics)". A null percentage renders empty/grey, not
 *  0%: "an empty subject shouldn't look '0% learned'." */
function Bar({ pct }: { pct: number | null }) {
  if (pct === null) {
    return (
      <span data-testid="progress-bar" data-pct="none"
            className="flex shrink-0 items-center gap-2">
        <span className="h-1.5 w-24 rounded-full bg-sunken" />
        <span className="w-9 text-right text-[0.6875rem] text-faint">—</span>
      </span>
    )
  }
  return (
    <span data-testid="progress-bar" data-pct={String(Math.round(pct))}
          className="flex shrink-0 items-center gap-2">
      <span className="h-1.5 w-24 overflow-hidden rounded-full bg-sunken">
        <span
          className="block h-full rounded-full bg-accent transition-[width]"
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className="w-9 text-right text-[0.6875rem] tabular-nums text-muted">
        {Math.round(pct)}%
      </span>
    </span>
  )
}

/** One row: collapse it, open it by name, add inside it, delete it, drag it. */
function PageRow({ kind, id, name, pct, level, addLabel, onAdd, onDeleted,
                  trailing, collapsed, onToggle, drag }: {
  kind: TreeKind
  id: number
  name: string
  pct?: number | null
  level: 0 | 1 | 2 | 3
  addLabel?: string
  onAdd?: () => void
  onDeleted: () => void | Promise<void>
  trailing?: React.ReactNode
  collapsed?: boolean
  onToggle?: () => void
  drag?: DragHandlers
}) {
  const openPage = useUI((s) => s.openPage)
  const size = ['text-[0.9375rem] font-semibold', 'text-[0.875rem] font-medium',
                'text-[0.8125rem]', 'text-[0.8125rem]'][level]

  return (
    <div
      {...(drag?.props ?? {})}
      className={[
        'group flex items-center gap-2 rounded-md px-1 py-0.5 transition hover:bg-paper',
        drag?.over ? 'ring-1 ring-accent' : '',
      ].join(' ')}
    >
      {onToggle && (
        <button
          type="button"
          onClick={onToggle}
          data-testid={`roadmap-collapse-${kind}-${id}`}
          aria-label={`${collapsed ? 'Expand' : 'Collapse'} ${name}`}
          aria-expanded={!collapsed}
          className="grid size-4 shrink-0 place-items-center rounded text-faint transition hover:bg-sunken"
        >
          <svg width="9" height="9" viewBox="0 0 10 10" fill="none" aria-hidden="true"
               className={`transition-transform ${collapsed ? '' : 'rotate-90'}`}>
            <path d="m3.5 2 3.5 3-3.5 3" stroke="currentColor" strokeWidth="1.3"
                  strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
      {trailing}
      <button
        type="button"
        onClick={() => openPage(kind, id)}
        data-testid={`roadmap-open-${kind}-${id}`}
        className={`min-w-0 flex-1 truncate text-left text-ink transition hover:text-accent-deep ${size}`}
      >
        {name}
      </button>
      {addLabel && onAdd && (
        <AddButton label={addLabel} onClick={onAdd} testid={`add-${kind}-child-${id}`} />
      )}
      <DeleteButton kind={kind} id={id} name={name} onDeleted={onDeleted} />
      {pct !== undefined && <Bar pct={pct} />}
    </div>
  )
}

// --------------------------------------------------------------------------
// Dragging
//
// The same POST /api/tree/move the sidebar uses: dropping a row on another of
// its own kind puts it in that position, and the server renumbers the run.
// --------------------------------------------------------------------------

type Dragged = { kind: TreeKind; id: number; parentId: number | null; subtopicId: number | null }
type DragHandlers = { props: Record<string, unknown>; over: boolean }

const MIME = 'application/x-rnl-roadmap'

function useDragRow(self: Dragged, index: number): DragHandlers {
  const [over, setOver] = useState(false)
  const refresh = useRefreshEverything()
  const move = useMutation({ mutationFn: api.moveTreeItem, onSuccess: refresh })

  return {
    over,
    props: {
      draggable: true,
      onDragStart: (e: React.DragEvent) => {
        e.dataTransfer.setData(MIME, JSON.stringify(self))
        e.dataTransfer.effectAllowed = 'move'
      },
      onDragOver: (e: React.DragEvent) => {
        if (!e.dataTransfer.types.includes(MIME)) return
        e.preventDefault()
        setOver(true)
      },
      onDragLeave: () => setOver(false),
      onDrop: (e: React.DragEvent) => {
        setOver(false)
        let drag: Dragged
        try {
          drag = JSON.parse(e.dataTransfer.getData(MIME)) as Dragged
        } catch {
          return
        }
        // Same kind only: a lesson dropped on a topic is ambiguous — into it,
        // or before it? Reparenting has its own control ("Move to…").
        if (drag.kind !== self.kind || drag.id === self.id) return
        e.preventDefault()
        e.stopPropagation()
        move.mutate({
          kind: drag.kind, id: drag.id,
          parent_id: self.parentId, subtopic_id: self.subtopicId,
          position: index,
        })
      },
    },
  }
}

// --------------------------------------------------------------------------
// The tree
// --------------------------------------------------------------------------

function SubjectBlock({ subject, index }: { subject: RoadmapSubject; index: number }) {
  const refresh = useRefreshEverything()
  const [adding, setAdding] = useState(false)
  const collapsed = useUI((s) => s.collapsedRows.includes(`subject-${subject.id}`))
  const toggleRow = useUI((s) => s.toggleRow)
  const drag = useDragRow(
    { kind: 'subject', id: subject.id, parentId: null, subtopicId: null }, index)

  const addTopic = useMutation({
    mutationFn: (name: string) => api.createTopic(subject.id, name),
    onSuccess: refresh,
  })

  return (
    <section
      data-testid={`roadmap-subject-${subject.id}`}
      className="rounded-lg border border-line bg-surface p-4"
    >
      <PageRow
        kind="subject" id={subject.id} name={subject.name} pct={subject.pct}
        level={0} addLabel="Topic" onAdd={() => setAdding(true)}
        onDeleted={refresh}
        collapsed={collapsed} onToggle={() => toggleRow(`subject-${subject.id}`)}
        drag={drag}
        trailing={
          <span className="size-2 shrink-0 rounded-full"
                style={{ background: subject.colour ?? 'var(--color-faint)' }}
                aria-hidden="true" />
        }
      />
      {adding && (
        <NameInput placeholder="Topic name" testid={`new-topic-${subject.id}`}
                   onCancel={() => setAdding(false)}
                   onSubmit={(name) => addTopic.mutate(name)} indent="ml-3" />
      )}

      {!collapsed && (
        <div className="mt-3 space-y-3">
          {subject.topics.map((topic, i) => (
            <TopicBlock key={topic.id} topic={topic} index={i}
                        subjectId={subject.id} />
          ))}
        </div>
      )}
    </section>
  )
}

function TopicBlock({ topic, index, subjectId }: {
  topic: RoadmapSubject['topics'][number]
  index: number
  subjectId: number
}) {
  const refresh = useRefreshEverything()
  const [adding, setAdding] = useState<'subtopic' | 'lesson' | null>(null)
  const collapsed = useUI((s) => s.collapsedRows.includes(`topic-${topic.id}`))
  const toggleRow = useUI((s) => s.toggleRow)
  const drag = useDragRow(
    { kind: 'topic', id: topic.id, parentId: subjectId, subtopicId: null }, index)

  const addSubtopic = useMutation({
    mutationFn: (name: string) => api.createSubtopic(topic.id, name),
    onSuccess: refresh,
  })
  const addLesson = useMutation({
    mutationFn: (name: string) => api.createLesson({ topic_id: topic.id, name }),
    onSuccess: refresh,
  })

  return (
    <div data-testid={`roadmap-topic-${topic.id}`}>
      <PageRow
        kind="topic" id={topic.id} name={topic.name} pct={topic.pct} level={1}
        addLabel="Subtopic" onAdd={() => setAdding('subtopic')}
        onDeleted={refresh}
        collapsed={collapsed} onToggle={() => toggleRow(`topic-${topic.id}`)}
        drag={drag}
      />
      {adding === 'subtopic' && (
        <NameInput placeholder="Subtopic name" testid={`new-subtopic-${topic.id}`}
                   onCancel={() => setAdding(null)}
                   onSubmit={(name) => addSubtopic.mutate(name)} indent="ml-3" />
      )}

      {/* Lessons hanging straight off the topic, with no subtopic. */}
      {!collapsed && topic.lessons.length > 0 && (
        <ul className="ml-3 mt-1 space-y-0.5 border-l border-line-soft pl-2">
          {topic.lessons.map((lesson, i) => (
            <LessonRow key={lesson.id} lesson={lesson} index={i}
                       topicId={topic.id} subtopicId={null} />
          ))}
        </ul>
      )}

      {!collapsed && (
        <div className="ml-3 mt-1 space-y-2 border-l border-line-soft pl-2">
          {topic.subtopics.map((subtopic, i) => (
            <SubtopicBlock key={subtopic.id} subtopic={subtopic}
                           topicId={topic.id} index={i} />
          ))}
        </div>
      )}

      {collapsed ? null : adding === 'lesson' ? (
        <NameInput placeholder="Lesson name" testid={`new-lesson-topic-${topic.id}`}
                   onCancel={() => setAdding(null)}
                   onSubmit={(name) => addLesson.mutate(name)} indent="ml-5" />
      ) : (
        <button
          type="button"
          onClick={() => setAdding('lesson')}
          data-testid={`add-lesson-topic-${topic.id}`}
          className="ml-5 mt-1 text-[0.75rem] text-faint transition hover:text-accent-deep"
        >
          + Lesson here
        </button>
      )}
    </div>
  )
}

function SubtopicBlock({ subtopic, topicId, index }: {
  subtopic: RoadmapSubject['topics'][number]['subtopics'][number]
  topicId: number
  index: number
}) {
  const refresh = useRefreshEverything()
  const [adding, setAdding] = useState(false)
  const collapsed = useUI((s) => s.collapsedRows.includes(`subtopic-${subtopic.id}`))
  const toggleRow = useUI((s) => s.toggleRow)
  const drag = useDragRow(
    { kind: 'subtopic', id: subtopic.id, parentId: topicId, subtopicId: null }, index)

  const addLesson = useMutation({
    mutationFn: (name: string) =>
      api.createLesson({ topic_id: topicId, subtopic_id: subtopic.id, name }),
    onSuccess: refresh,
  })

  return (
    <div data-testid={`roadmap-subtopic-${subtopic.id}`}>
      <PageRow
        kind="subtopic" id={subtopic.id} name={subtopic.name} pct={subtopic.pct}
        level={2} addLabel="Lesson" onAdd={() => setAdding(true)}
        onDeleted={refresh}
        collapsed={collapsed}
        onToggle={subtopic.lessons.length > 0
          ? () => toggleRow(`subtopic-${subtopic.id}`) : undefined}
        drag={drag}
      />

      {!collapsed && subtopic.lessons.length > 0 && (
        <ul className="ml-3 mt-1 space-y-0.5">
          {subtopic.lessons.map((lesson, i) => (
            <LessonRow key={lesson.id} lesson={lesson} index={i}
                       topicId={topicId} subtopicId={subtopic.id} />
          ))}
        </ul>
      )}

      {adding && (
        <NameInput placeholder="Lesson name"
                   testid={`add-lesson-subtopic-${subtopic.id}`}
                   onCancel={() => setAdding(false)}
                   onSubmit={(name) => addLesson.mutate(name)} indent="ml-3" />
      )}
    </div>
  )
}

function LessonRow({ lesson, index, topicId, subtopicId }: {
  lesson: RoadmapLesson
  index: number
  topicId: number
  subtopicId: number | null
}) {
  const qc = useQueryClient()
  const refresh = useRefreshEverything()
  const [open, setOpen] = useState(false)
  const openPage = useUI((s) => s.openPage)
  const drag = useDragRow(
    { kind: 'lesson', id: lesson.id, parentId: topicId, subtopicId }, index)

  const setStatus = useMutation({
    mutationFn: (status: string) => api.updateLesson(lesson.id, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['roadmap'] }),
  })
  // Consolidated addendum §2 — ticking here writes to the *note block* the
  // item came from; `checklist_items` is a projection, never a second copy.
  const toggleItem = useMutation({
    mutationFn: ({ itemId, done }: { itemId: number; done: boolean }) =>
      api.toggleChecklistItem(itemId, done),
    onSuccess: refresh,
  })

  const next = STATUS_CYCLE[lesson.status] ?? 'in_progress'
  const style = STATUS_STYLE[lesson.status] ?? STATUS_STYLE.not_started

  return (
    <li data-testid={`lesson-${lesson.id}`} data-status={lesson.status}>
      <div
        {...drag.props}
        className={[
          'group flex items-center gap-2 rounded-md px-1 py-0.5 transition',
          style.row || 'hover:bg-paper',
          drag.over ? 'ring-1 ring-accent' : '',
        ].join(' ')}
      >
        <button
          type="button"
          onClick={() => setStatus.mutate(next)}
          data-testid={`lesson-status-${lesson.id}`}
          aria-label={`${lesson.name} is ${style.label} — mark ${(STATUS_STYLE[next] ?? STATUS_STYLE.not_started).label}`}
          title={style.label}
          className={[
            'grid size-4 shrink-0 place-items-center rounded border text-[0.5625rem] font-semibold transition',
            style.box,
          ].join(' ')}
        >
          {STATUS_MARK[lesson.status] ?? '·'}
        </button>

        {lesson.items.length > 0 && (
          <button
            type="button"
            onClick={() => setOpen(!open)}
            data-testid={`lesson-chevron-${lesson.id}`}
            aria-label={`${open ? 'Hide' : 'Show'} ${lesson.name} checklist`}
            aria-expanded={open}
            className="grid size-4 shrink-0 place-items-center rounded text-faint transition hover:bg-sunken"
          >
            <svg width="9" height="9" viewBox="0 0 10 10" fill="none" aria-hidden="true"
                 className={`transition-transform ${open ? 'rotate-90' : ''}`}>
              <path d="m3.5 2 3.5 3-3.5 3" stroke="currentColor" strokeWidth="1.3"
                    strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}

        <button
          type="button"
          onClick={() => openPage('lesson', lesson.id)}
          data-testid={`lesson-name-${lesson.id}`}
          className="min-w-0 flex-1 truncate text-left text-[0.8125rem] text-ink transition hover:text-accent-deep"
        >
          {lesson.name}
          {lesson.items.length > 0 && (
            <span className="ml-1.5 text-[0.6875rem] text-faint">
              {lesson.items.filter((i) => i.done).length}/{lesson.items.length}
            </span>
          )}
        </button>

        <DeleteButton kind="lesson" id={lesson.id} name={lesson.name}
                      onDeleted={refresh} />
        <Bar pct={lesson.pct} />
      </div>

      {open && (
        <ul className="ml-6 mt-1 space-y-0.5">
          {lesson.items.map((item) => (
            <li key={item.id} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={item.done}
                data-testid={`item-${item.id}`}
                onChange={(e) =>
                  toggleItem.mutate({ itemId: item.id, done: e.target.checked })
                }
                className="size-3.5 accent-[var(--color-accent)]"
              />
              <span className={`text-[0.8125rem] ${item.done ? 'text-faint line-through' : 'text-ink-soft'}`}>
                {item.title}
              </span>
            </li>
          ))}
          {/* §2 — "This table has no dedicated CRUD UI. The only way to
              create or edit a checklist item is by typing … inside the note
              editor." So this points at the note instead of pretending. */}
          <li>
            <button
              type="button"
              onClick={() => openPage('lesson', lesson.id)}
              data-testid={`lesson-write-items-${lesson.id}`}
              className="px-1.5 py-1 text-[0.75rem] text-faint transition hover:text-accent-deep"
            >
              Write items in the note →
            </button>
          </li>
        </ul>
      )}
    </li>
  )
}

// --------------------------------------------------------------------------

/** One row's identity on the board: kind and id together, because a lesson
 *  and a todo can share an id. */
const keyOf = (entry: { kind: string; id: number }) => `${entry.kind}-${entry.id}`

/** Todos (addendum §6) — "a flat, filterable, cross-cutting list combining
 *  standalone Todos and any open Lesson/Item across every subject. This is the
 *  view with the hide-completed toggle, default on." */
export function Todos() {
  const qc = useQueryClient()
  const refresh = useRefreshEverything()
  const [hideCompleted, setHideCompleted] = useState(true)
  /** Selection, keyed "kind-id", and whether we are selecting at all.
   *
   *  Two checkboxes on one row — one to select, one to tick off — is a
   *  puzzle: neither is obviously the one you meant. So a row has exactly one
   *  checkbox at a time. Normally it completes the todo, which is what a
   *  checkbox next to a task means everywhere else; in Select mode it selects,
   *  and the bulk actions appear. */
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const stopSelecting = () => {
    setSelecting(false)
    setSelected(new Set())
  }
  const [subjectId, setSubjectId] = useState<number | ''>('')
  const [dueOnly, setDueOnly] = useState(false)
  const [title, setTitle] = useState('')
  const [due, setDue] = useState('')

  const { data: subjects = [] } = useQuery({
    queryKey: ['subjects'],
    queryFn: api.subjects,
  })
  const { data } = useQuery({
    queryKey: ['todo-board', hideCompleted, subjectId, dueOnly],
    queryFn: () =>
      api.todoBoard({
        hide_completed: hideCompleted,
        ...(subjectId === '' ? {} : { subject_id: subjectId }),
        ...(dueOnly ? { has_due_date: true } : {}),
      }),
  })

  const add = useMutation({
    mutationFn: () =>
      api.createTodo({
        title: title.trim(),
        due_date: due || null,
        ...(subjectId === '' ? {} : { subject_id: subjectId }),
      }),
    onSuccess: async () => {
      setTitle('')
      setDue('')
      await qc.invalidateQueries({ queryKey: ['todo-board'] })
    },
  })

  const entries = data?.entries ?? []
  const allSelected = entries.length > 0 && entries.every((e) => selected.has(keyOf(e)))
  const someSelected = selected.size > 0
  const selectedTodoIds = entries
    .filter((e) => selected.has(keyOf(e)))
    .map((e) => e.id)

  /** Bulk toggles run one after another rather than all at once: SQLite has a
   *  single writer, and a dozen parallel writes would just queue behind each
   *  other with less to show for it. */
  const bulkDone = useMutation({
    mutationFn: async (done: boolean) => {
      for (const entry of entries) {
        if (!selected.has(keyOf(entry)) || entry.done === done) continue
        await api.updateTodo(entry.id, { done })
      }
    },
    onSuccess: async () => { stopSelecting(); await refresh() },
  })

  const bulkDelete = useMutation({
    mutationFn: async () => {
      for (const id of selectedTodoIds) await api.deleteTodo(id)
    },
    onSuccess: async () => { stopSelecting(); await refresh() },
  })

  const toggle = useMutation({
    // Only the user's own todos live here now, so there is one thing a tick
    // can mean. Lessons and checklist items are managed where they live.
    mutationFn: (entry: { id: number; done: boolean }) =>
      api.updateTodo(entry.id, { done: !entry.done }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['todo-board'] })
      await qc.invalidateQueries({ queryKey: ['roadmap'] })
    },
  })

  return (
    <div data-testid="todos" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <h2 className="text-xl font-semibold tracking-tight text-ink">Todos</h2>
      <p className="mt-1 text-[0.875rem] leading-relaxed text-muted">
        Your own list. Lessons live in the Roadmap; nothing here is written
        by the app.
      </p>

      <form
        onSubmit={(e) => { e.preventDefault(); if (title.trim()) add.mutate() }}
        className="mt-4 flex flex-wrap items-center gap-2"
      >
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Add a todo"
          data-testid="todo-input"
          className="min-w-0 flex-1 rounded-md border border-line bg-paper px-2.5 py-1.5 text-[0.875rem] text-ink outline-none focus:border-accent focus:bg-surface"
        />
        <input
          type="date"
          value={due}
          onChange={(e) => setDue(e.target.value)}
          data-testid="todo-due"
          className="rounded-md border border-line bg-paper px-2 py-1.5 text-[0.8125rem] text-ink outline-none focus:border-accent"
        />
        <button
          type="submit"
          disabled={!title.trim() || add.isPending}
          data-testid="todo-add"
          className="rounded-md bg-accent px-3 py-1.5 text-[0.8125rem] font-medium text-white transition hover:bg-accent-deep disabled:opacity-40"
        >
          Add
        </button>
      </form>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-[0.75rem]">
        <label className="flex items-center gap-1.5 text-muted">
          <input
            type="checkbox"
            checked={hideCompleted}
            data-testid="hide-completed"
            onChange={(e) => setHideCompleted(e.target.checked)}
            className="size-3.5 accent-[var(--color-accent)]"
          />
          Hide completed
        </label>
        <label className="flex items-center gap-1.5 text-muted">
          <input
            type="checkbox"
            checked={dueOnly}
            data-testid="due-only"
            onChange={(e) => setDueOnly(e.target.checked)}
            className="size-3.5 accent-[var(--color-accent)]"
          />
          Has a due date
        </label>
        <select
          value={subjectId}
          data-testid="todo-subject-filter"
          onChange={(e) => setSubjectId(e.target.value ? Number(e.target.value) : '')}
          className="rounded-md border border-line bg-paper px-2 py-1 text-[0.75rem] text-ink outline-none focus:border-accent"
        >
          <option value="">All subjects</option>
          {subjects.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
      </div>

      {(data?.entries.length ?? 0) === 0 ? (
        <p data-testid="todos-empty" className="mt-5 rounded-lg border border-dashed border-line bg-surface p-8 text-center text-[0.875rem] text-faint">
          Nothing open.
        </p>
      ) : (
        <>
        <div className="mt-4 flex flex-wrap items-center gap-2 border-b border-line-soft pb-2">
          {selecting ? (
            <>
              <label className="flex items-center gap-1.5 text-[0.75rem] text-muted">
                <input
                  type="checkbox"
                  data-testid="todo-select-all"
                  checked={allSelected}
                  ref={(el) => { if (el) el.indeterminate = someSelected && !allSelected }}
                  onChange={(e) => {
                    setSelected(e.target.checked
                      ? new Set((data?.entries ?? []).map(keyOf))
                      : new Set())
                  }}
                  className="size-3.5 accent-[var(--color-accent)]"
                />
                Select all
              </label>

              <span data-testid="todo-selection" className="flex flex-wrap items-center gap-2 text-[0.75rem]">
                <span className="text-muted">{selected.size} selected</span>
                <button
                  type="button"
                  disabled={selected.size === 0}
                  onClick={() => bulkDone.mutate(true)}
                  data-testid="todo-bulk-done"
                  className="rounded border border-emerald-600 px-2 py-0.5 text-emerald-700 transition hover:bg-emerald-50 disabled:opacity-40"
                >
                  Mark done
                </button>
                <button
                  type="button"
                  disabled={selected.size === 0}
                  onClick={() => bulkDone.mutate(false)}
                  data-testid="todo-bulk-open"
                  className="rounded border border-amber-500 px-2 py-0.5 text-amber-700 transition hover:bg-amber-50 disabled:opacity-40"
                >
                  Mark open
                </button>
                <button
                  type="button"
                  disabled={selectedTodoIds.length === 0}
                  onClick={() => bulkDelete.mutate()}
                  data-testid="todo-bulk-delete"
                  className="rounded border border-stale px-2 py-0.5 text-stale transition hover:bg-stale-wash disabled:opacity-40"
                >
                  Delete{selectedTodoIds.length > 0 ? ` ${selectedTodoIds.length}` : ''}
                </button>
              </span>

              <button
                type="button"
                onClick={stopSelecting}
                data-testid="todo-select-done"
                className="ml-auto rounded px-2 py-0.5 text-[0.75rem] text-muted transition hover:bg-sunken hover:text-ink"
              >
                Done
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setSelecting(true)}
              data-testid="todo-select-mode"
              className="ml-auto rounded px-2 py-0.5 text-[0.75rem] text-muted transition hover:bg-sunken hover:text-ink"
            >
              Select
            </button>
          )}
        </div>

        <ul className="mt-2 space-y-1" data-testid="todo-entries">
          {data!.entries.map((entry) => (
            <li
              key={`${entry.kind}-${entry.id}`}
              data-testid={`entry-${entry.kind}-${entry.id}`}
              data-done={entry.done ? 'true' : 'false'}
              className={[
                'group flex items-center gap-2.5 rounded-md px-2 py-1.5',
                // Open is amber, finished is green — the same language the
                // Roadmap uses for a lesson, so one glance reads the same way
                // in both places.
                entry.done ? 'bg-emerald-50/70' : 'bg-amber-50/60',
              ].join(' ')}
            >
              {selecting ? (
                <input
                  type="checkbox"
                  checked={selected.has(keyOf(entry))}
                  onChange={(e) => {
                    setSelected((current) => {
                      const next = new Set(current)
                      if (e.target.checked) next.add(keyOf(entry))
                      else next.delete(keyOf(entry))
                      return next
                    })
                  }}
                  data-testid={`select-${entry.kind}-${entry.id}`}
                  aria-label={`Select ${entry.title}`}
                  className="size-3.5 shrink-0 accent-[var(--color-accent)]"
                />
              ) : (
                <input
                  type="checkbox"
                  checked={entry.done}
                  onChange={() => toggle.mutate(entry)}
                  data-testid={`done-${entry.kind}-${entry.id}`}
                  aria-label={entry.title}
                  className={`size-3.5 shrink-0 ${entry.done ? 'accent-emerald-600' : 'accent-amber-500'}`}
                />
              )}
              <span className={`min-w-0 flex-1 truncate text-[0.8125rem] ${entry.done ? 'text-faint line-through' : 'text-ink'}`}>
                {entry.title}
              </span>
              {/* Every row is the user's own todo, so every row can go. */}
              {!selecting && <DeleteTodo id={entry.id} title={entry.title} />}
              {entry.due_date && (
                <span className="shrink-0 text-[0.6875rem] tabular-nums text-muted">
                  {entry.due_date}
                </span>
              )}
            </li>
          ))}
        </ul>
        </>
      )}
    </div>
  )
}


/** Deleting a standalone todo, behind one confirmation. Soft, like everything
 *  else (principle §1.7): the row goes, the record does not. */
function DeleteTodo({ id, title }: { id: number; title: string }) {
  const [confirming, setConfirming] = useState(false)
  const refresh = useRefreshEverything()

  const remove = useMutation({
    mutationFn: () => api.deleteTodo(id),
    onSuccess: async () => { setConfirming(false); await refresh() },
  })

  if (confirming) {
    return (
      <span className="flex shrink-0 items-center gap-1 text-[0.6875rem]">
        <button
          type="button"
          onClick={() => remove.mutate()}
          disabled={remove.isPending}
          data-testid={`todo-delete-confirm-${id}`}
          className="rounded bg-stale px-1.5 py-0.5 font-medium text-white disabled:opacity-50"
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
    )
  }

  return (
    <button
      type="button"
      onClick={() => setConfirming(true)}
      data-testid={`todo-delete-${id}`}
      aria-label={`Delete ${title}`}
      title={`Delete ${title}`}
      // Always visible here, unlike the Roadmap's: this is a list you come to
      // in order to prune, not one you pass through on the way somewhere.
      className="grid size-5 shrink-0 place-items-center rounded text-faint transition hover:bg-sunken hover:text-stale"
    >
      <svg width="11" height="11" viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path d="M2.5 3.5h7M5 3V2h2v1M4 3.5l.4 6h3.2l.4-6"
              stroke="currentColor" strokeWidth="1.1"
              strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  )
}
