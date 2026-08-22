import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type RoadmapLesson, type RoadmapSubject } from '../lib/api'
import { useOpenLesson } from '../lib/openLesson'

/** Roadmap (addendum §6) — the full tree with percentage bars at every level.
 *
 *  "Always shows everything, completed included — no hide-completed toggle
 *  here; seeing the whole shape of a curriculum, finished parts included, is
 *  the point of this view."
 *
 *  Addendum §5 **[LOCKED]**: these bars must not share a visual language with
 *  FSRS mastery badges. A grey track with a single accent fill, no
 *  traffic-light colour, no badge words. A green 100% here would quietly teach
 *  that finishing a checklist is the same as knowing the material.
 */
export function Roadmap() {
  const { data, isLoading } = useQuery({
    queryKey: ['roadmap'],
    queryFn: api.roadmap,
  })

  return (
    <div data-testid="roadmap" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <h2 className="text-xl font-semibold tracking-tight text-ink">Roadmap</h2>
      <p className="mt-1 text-[0.875rem] leading-relaxed text-muted">
        What you have worked through. Ticking a box tracks progress through
        material, not what you know — those two are deliberately separate.
      </p>

      {isLoading ? (
        <p className="mt-5 text-[0.8125rem] text-faint">Loading…</p>
      ) : (data?.subjects.length ?? 0) === 0 ? (
        <p data-testid="roadmap-empty" className="mt-5 rounded-lg border border-dashed border-line bg-surface p-8 text-center text-[0.875rem] text-faint">
          No subjects yet. Add one in the sidebar, then add lessons here.
        </p>
      ) : (
        <div className="mt-5 space-y-4">
          {data!.subjects.map((subject) => (
            <SubjectBlock key={subject.id} subject={subject} />
          ))}
        </div>
      )}
    </div>
  )
}

function SubjectBlock({ subject }: { subject: RoadmapSubject }) {
  return (
    <section
      data-testid={`roadmap-subject-${subject.id}`}
      className="rounded-lg border border-line bg-surface p-4"
    >
      <Row name={subject.name} pct={subject.pct} level={0} />
      <div className="mt-3 space-y-3">
        {subject.topics.map((topic) => (
          <div key={topic.id} data-testid={`roadmap-topic-${topic.id}`}>
            <Row name={topic.name} pct={topic.pct} level={1} />

            {/* Lessons hanging straight off the topic, with no subtopic. */}
            {topic.lessons.length > 0 && (
              <ul className="ml-3 mt-1.5 space-y-1">
                {topic.lessons.map((lesson) => (
                  <LessonRow key={lesson.id} lesson={lesson} />
                ))}
              </ul>
            )}
            <Builder topicId={topic.id} subtopicId={null} />

            <div className="ml-3 mt-2 space-y-2">
              {topic.subtopics.map((subtopic) => (
                <div key={subtopic.id} data-testid={`roadmap-subtopic-${subtopic.id}`}>
                  <Row name={subtopic.name} pct={subtopic.pct} level={2} />
                  <ul className="ml-3 mt-1.5 space-y-1">
                    {subtopic.lessons.map((lesson) => (
                      <LessonRow key={lesson.id} lesson={lesson} />
                    ))}
                  </ul>
                  <Builder topicId={topic.id} subtopicId={subtopic.id} />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function Row({ name, pct, level }: {
  name: string
  pct: number | null
  level: number
}) {
  const size = ['text-[0.9375rem] font-semibold', 'text-[0.875rem] font-medium',
                'text-[0.8125rem]'][level]
  return (
    <div className="flex items-center gap-3">
      <span className={`min-w-0 flex-1 truncate text-ink ${size}`}>{name}</span>
      <Bar pct={pct} />
    </div>
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

function LessonRow({ lesson }: { lesson: RoadmapLesson }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const openLesson = useOpenLesson()

  const setStatus = useMutation({
    mutationFn: (status: string) => api.updateLesson(lesson.id, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['roadmap'] }),
  })
  // Consolidated addendum §2 — ticking here writes to the *note block* the
  // item came from; `checklist_items` is a projection, never a second copy.
  const toggleItem = useMutation({
    mutationFn: ({ itemId, done }: { itemId: number; done: boolean }) =>
      api.toggleChecklistItem(itemId, done),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['roadmap'] }),
  })

  const next = { not_started: 'in_progress', in_progress: 'done',
                 done: 'not_started' }[lesson.status] ?? 'not_started'

  return (
    <li data-testid={`lesson-${lesson.id}`} data-status={lesson.status}>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setStatus.mutate(next)}
          data-testid={`lesson-status-${lesson.id}`}
          aria-label={`Mark ${lesson.name} ${next.replace('_', ' ')}`}
          className={[
            'grid size-4 shrink-0 place-items-center rounded border text-[0.5625rem] transition',
            lesson.status === 'done'
              ? 'border-accent bg-accent text-white'
              : lesson.status === 'in_progress'
                ? 'border-accent text-accent-deep'
                : 'border-line text-transparent hover:border-faint',
          ].join(' ')}
        >
          {lesson.status === 'done' ? '✓' : lesson.status === 'in_progress' ? '–' : '·'}
        </button>

        {/* §5 — the chevron previews in place; the name navigates. §3:
            "not a checklist-only expand like Roadmap currently does." */}
        {lesson.items.length > 0 && (
          <button
            type="button"
            onClick={() => setOpen(!open)}
            data-testid={`lesson-chevron-${lesson.id}`}
            aria-label={`${open ? 'Hide' : 'Show'} ${lesson.name} checklist`}
            aria-expanded={open}
            className="grid size-4 shrink-0 place-items-center rounded text-faint transition hover:bg-sunken"
          >
            <svg
              width="9" height="9" viewBox="0 0 10 10" fill="none" aria-hidden="true"
              className={`transition-transform ${open ? 'rotate-90' : ''}`}
            >
              <path d="m3.5 2 3.5 3-3.5 3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}

        <button
          type="button"
          onClick={() => void openLesson(lesson.id)}
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
              onClick={() => void openLesson(lesson.id)}
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

/** Addendum §7 **[LOCKED]** — the whole authoring flow, inline.
 *
 *  "Typing text and pressing Enter creates the Lesson and immediately opens a
 *  fresh '+ Add lesson' row below it, so multiple lessons can be added in a
 *  fast burst without re-clicking anything. Pressing Tab while adding a Lesson
 *  switches into 'add item' mode nested under the lesson just created …
 *  Shift+Tab or Escape pops back out."
 *
 *  No separate create dialog, no modal.
 */
function Builder({ topicId, subtopicId }: {
  topicId: number
  subtopicId: number | null
}) {
  const qc = useQueryClient()
  const [value, setValue] = useState('')
  const [lastLessonId, setLastLessonId] = useState<number | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const openLesson = useOpenLesson()

  const addLesson = useMutation({
    mutationFn: (name: string) =>
      api.createLesson({ topic_id: topicId, subtopic_id: subtopicId, name }),
    onSuccess: async (lesson) => {
      setLastLessonId(lesson.id)
      setValue('')
      await qc.invalidateQueries({ queryKey: ['roadmap'] })
      input.current?.focus()
    },
  })

  /** Enter still adds lesson after lesson in a burst. Tab used to switch into
   *  an "add item" mode; the consolidated addendum §2 removed that — items are
   *  checkboxes typed in a note — so Tab now opens the note of the lesson just
   *  created, which is where those items belong. */
  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      const text = value.trim()
      if (text) addLesson.mutate(text)
      return
    }
    if (e.key === 'Tab' && !e.shiftKey && lastLessonId !== null) {
      e.preventDefault()
      setValue('')
      void openLesson(lastLessonId)
    }
  }

  return (
    <div className="ml-3 mt-1">
      <input
        ref={input}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        data-testid={
          subtopicId === null
            ? `add-lesson-topic-${topicId}`
            : `add-lesson-subtopic-${subtopicId}`
        }
        data-mode="lesson"
        placeholder="+ Add lesson   (Enter to add, Tab to open its note)"
        className="w-full rounded-md border border-transparent bg-transparent px-1.5 py-1 text-[0.8125rem] text-ink outline-none transition placeholder:text-faint hover:border-line focus:border-accent focus:bg-paper"
      />
    </div>
  )
}

// --------------------------------------------------------------------------

/** Todos (addendum §6) — "a flat, filterable, cross-cutting list combining
 *  standalone Todos and any open Lesson/Item across every subject. This is the
 *  view with the hide-completed toggle, default on." */
export function Todos() {
  const qc = useQueryClient()
  const [hideCompleted, setHideCompleted] = useState(true)
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

  const toggle = useMutation({
    mutationFn: (entry: { kind: string; id: number; done: boolean; lesson_id: number | null }) => {
      if (entry.kind === 'todo') {
        return api.updateTodo(entry.id, { done: !entry.done })
      }
      if (entry.kind === 'lesson') {
        return api.updateLesson(entry.id, {
          status: entry.done ? 'not_started' : 'done',
        })
      }
      // A checklist entry is a note block behind the scenes (§2), so the
      // toggle goes through the projection's write-through endpoint.
      return api.toggleChecklistItem(entry.id, !entry.done)
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['todo-board'] })
      await qc.invalidateQueries({ queryKey: ['roadmap'] })
    },
  })

  return (
    <div data-testid="todos" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <h2 className="text-xl font-semibold tracking-tight text-ink">Todos</h2>
      <p className="mt-1 text-[0.875rem] leading-relaxed text-muted">
        Everything still open, across every subject.
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
        <ul className="mt-4 space-y-1" data-testid="todo-entries">
          {data!.entries.map((entry) => (
            <li
              key={`${entry.kind}-${entry.id}`}
              data-testid={`entry-${entry.kind}-${entry.id}`}
              className="flex items-center gap-2.5 rounded-md px-2 py-1.5 odd:bg-paper"
            >
              <input
                type="checkbox"
                checked={entry.done}
                onChange={() => toggle.mutate(entry)}
                aria-label={entry.title}
                className="size-3.5 shrink-0 accent-[var(--color-accent)]"
              />
              <span className={`min-w-0 flex-1 truncate text-[0.8125rem] ${entry.done ? 'text-faint line-through' : 'text-ink'}`}>
                {entry.title}
              </span>
              {entry.context && (
                <span className="hidden shrink-0 text-[0.6875rem] text-faint sm:inline">
                  {entry.context}
                </span>
              )}
              <span className="shrink-0 rounded bg-sunken px-1.5 py-0.5 text-[0.625rem] uppercase tracking-wide text-muted">
                {entry.kind === 'lesson_item' ? 'item' : entry.kind}
              </span>
              {entry.due_date && (
                <span className="shrink-0 text-[0.6875rem] tabular-nums text-muted">
                  {entry.due_date}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
