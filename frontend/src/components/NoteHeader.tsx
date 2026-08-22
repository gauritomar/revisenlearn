import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Note, type Subject } from '../lib/api'
import { useOpenLesson } from '../lib/openLesson'
import { useUI } from '../store/ui'
import { ProcessNotes } from './ProcessNotes'

/** The Notes screen header (spec §14): the note's title and date, the §4.2
 *  block counter, the save dot, and a **Process notes** button showing the
 *  unprocessed count.
 *
 *  §4.1 also lets the user create additional notes for a day and rename them,
 *  so the title is editable in place and siblings are switchable.
 */
export function NoteHeader({ note, saveState }: {
  note: Note
  saveState: string
}) {
  const qc = useQueryClient()
  const openSubtopic = useUI((s) => s.openSubtopic)
  const openLesson = useOpenLesson()
  const [moving, setMoving] = useState(false)
  const [naming, setNaming] = useState(false)

  // Consolidated addendum §3 — "A note tied to a Lesson has no name of its
  // own — it opens under the Lesson's name in the breadcrumb/header."
  const { data: subjects = [] } = useQuery({ queryKey: ['subjects'], queryFn: api.subjects })
  const lesson = note.lesson_id === null ? null : findLesson(subjects, note.lesson_id)

  // Sibling notes: same subtopic, same day. Only meaningful for subtopic
  // notes — a resource note is one per resource per day by definition.
  const { data: siblings = [] } = useQuery({
    queryKey: ['notes', 'siblings', note.subtopic_id, note.study_date],
    queryFn: () =>
      api.notes({ subtopic_id: note.subtopic_id!, study_date: note.study_date }),
    enabled: note.subtopic_id !== null && note.resource_id === null,
  })

  const rename = useMutation({
    mutationFn: (title: string) => api.updateNote(note.id, { title }),
    onSuccess: (updated) => {
      qc.setQueryData(['note', note.id], updated)
      void qc.invalidateQueries({ queryKey: ['notes'] })
      void qc.invalidateQueries({ queryKey: ['notes-by-date'] })
    },
  })

  // §3 — an additional note under the same lesson is "a deliberate hard
  // split, not the default", and "gets a real user-provided name, never an
  // auto-generated 'Note 2'". So this always asks for one.
  const addNote = useMutation({
    mutationFn: (title: string) =>
      api.createNote({
        subtopic_id: note.subtopic_id,
        topic_id: note.topic_id,
        study_date: note.study_date,
        title,
      }),
    onSuccess: async (created) => {
      setNaming(false)
      await qc.invalidateQueries({ queryKey: ['notes'] })
      qc.setQueryData(['note', created.id], created)
      openSubtopic(note.subtopic_id ?? -1, created.id)
    },
  })

  const pending = note.counts.new + note.counts.edited

  return (
    <div className="mb-4 border-b border-line-soft pb-3">
      {lesson && (
        <p data-testid="note-breadcrumb" className="mb-1 text-[0.75rem] text-faint">
          {lesson.path}
        </p>
      )}

      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {lesson ? (
          // The lesson names the note; renaming happens on the lesson.
          <h2 data-testid="note-title" className="text-lg font-semibold tracking-tight text-ink">
            {lesson.name}
          </h2>
        ) : (
          <EditableTitle
            key={note.id}
            value={note.title}
            onCommit={(title) => {
              if (title && title !== note.title) rename.mutate(title)
            }}
          />
        )}
        <time
          data-testid="note-date"
          dateTime={note.study_date}
          className="text-[0.8125rem] text-muted"
        >
          {formatStudyDate(note.study_date)}
        </time>

        <div className="ml-auto flex items-center gap-3">
          <BlockCounter counts={note.counts} />
          <SaveDot state={saveState} />
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        {/* Spec §14 — Process notes, showing the unprocessed count. */}
        <ProcessNotes pendingHint={pending} />

        {/* §5 — "Move to…" reaches the picker from inside the note, not only
            from the sidebar. */}
        {lesson && (
          <button
            type="button"
            onClick={() => setMoving(true)}
            data-testid="move-lesson"
            className="rounded-md px-2 py-1 text-[0.75rem] text-muted transition hover:bg-sunken hover:text-ink"
          >
            Move to…
          </button>
        )}

        {note.resource_id === null && note.subtopic_id !== null && (
          <>
            {siblings.length > 1 && (
              <div className="flex flex-wrap items-center gap-1" data-testid="note-siblings">
                {siblings.map((s, i) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => openSubtopic(note.subtopic_id ?? -1, s.id)}
                    data-testid={`sibling-${s.id}`}
                    className={[
                      'rounded px-1.5 py-0.5 text-[0.6875rem] transition',
                      s.id === note.id
                        ? 'bg-accent-wash font-medium text-accent-deep'
                        : 'text-muted hover:bg-sunken hover:text-ink',
                    ].join(' ')}
                  >
                    {i + 1}
                  </button>
                ))}
              </div>
            )}
            {naming ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  const input = e.currentTarget.elements.namedItem('title') as HTMLInputElement
                  const title = input.value.trim()
                  if (title) addNote.mutate(title)
                }}
                className="flex items-center gap-1"
              >
                <input
                  name="title"
                  autoFocus
                  data-testid="new-note-name"
                  placeholder="Name this note"
                  onKeyDown={(e) => { if (e.key === 'Escape') setNaming(false) }}
                  className="w-40 rounded border border-accent bg-surface px-1.5 py-0.5 text-[0.75rem] text-ink outline-none"
                />
                <button
                  type="submit"
                  disabled={addNote.isPending}
                  data-testid="new-note-create"
                  className="rounded bg-accent px-1.5 py-0.5 text-[0.6875rem] font-medium text-white disabled:opacity-50"
                >
                  Create
                </button>
              </form>
            ) : (
              <button
                type="button"
                onClick={() => setNaming(true)}
                data-testid="new-note"
                className="rounded-md px-2 py-1 text-[0.75rem] text-muted transition hover:bg-sunken hover:text-ink"
              >
                + New note
              </button>
            )}
          </>
        )}
      </div>

      {moving && lesson && (
        <MovePicker
          lessonId={lesson.id}
          subjects={subjects}
          onClose={() => setMoving(false)}
          onMoved={async () => {
            setMoving(false)
            await qc.invalidateQueries({ queryKey: ['subjects'] })
            await qc.invalidateQueries({ queryKey: ['roadmap'] })
            await openLesson(lesson.id)
          }}
        />
      )}
    </div>
  )
}

/** Where a lesson sits, for the breadcrumb. */
function findLesson(subjects: Subject[], lessonId: number) {
  for (const subject of subjects) {
    for (const topic of subject.topics) {
      for (const lesson of topic.lessons) {
        if (lesson.id === lessonId) {
          return { ...lesson, path: `${subject.name} › ${topic.name}` }
        }
      }
      for (const subtopic of topic.subtopics) {
        for (const lesson of subtopic.lessons) {
          if (lesson.id === lessonId) {
            return {
              ...lesson,
              path: `${subject.name} › ${topic.name} › ${subtopic.name}`,
            }
          }
        }
      }
    }
  }
  return null
}

/** §5 — "a **"Move to..."** action … that reparents it to a different
 *  Subject/Topic/Subtopic via a picker — covers reordering without requiring
 *  precise drag targeting." */
function MovePicker({ lessonId, subjects, onClose, onMoved }: {
  lessonId: number
  subjects: Subject[]
  onClose: () => void
  onMoved: () => void | Promise<void>
}) {
  const [query, setQuery] = useState('')

  const destinations: Array<{
    key: string; path: string; topicId: number; subtopicId: number | null
  }> = []
  for (const subject of subjects) {
    for (const topic of subject.topics) {
      destinations.push({
        key: `t-${topic.id}`, path: `${subject.name} › ${topic.name}`,
        topicId: topic.id, subtopicId: null,
      })
      for (const subtopic of topic.subtopics) {
        destinations.push({
          key: `st-${subtopic.id}`,
          path: `${subject.name} › ${topic.name} › ${subtopic.name}`,
          topicId: topic.id, subtopicId: subtopic.id,
        })
      }
    }
  }
  const q = query.trim().toLowerCase()
  const shown = (q ? destinations.filter((d) => d.path.toLowerCase().includes(q)) : destinations)
    .slice(0, 10)

  const move = useMutation({
    mutationFn: (d: { topicId: number; subtopicId: number | null }) =>
      api.moveTreeItem({
        kind: 'lesson', id: lessonId,
        parent_id: d.topicId, subtopic_id: d.subtopicId, position: 9999,
      }),
    onSuccess: onMoved,
  })

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-ink/15 px-4 pt-[14vh] backdrop-blur-[2px]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Move this lesson"
        data-testid="move-picker"
        className="w-full max-w-md rounded-xl border border-line bg-surface p-4 shadow-xl"
      >
        <h2 className="text-[0.9375rem] font-semibold tracking-tight text-ink">Move to…</h2>
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Escape') onClose() }}
          data-testid="move-search"
          placeholder="Search topics and subtopics…"
          className="mt-3 w-full rounded-md border border-line bg-paper px-2.5 py-1.5 text-[0.8125rem] text-ink outline-none transition placeholder:text-faint focus:border-accent"
        />
        <ul className="mt-2 max-h-56 overflow-y-auto rounded-md border border-line-soft">
          {shown.length === 0 ? (
            <li className="px-2.5 py-2 text-[0.75rem] text-faint">Nothing matches.</li>
          ) : (
            shown.map((d) => (
              <li key={d.key}>
                <button
                  type="button"
                  disabled={move.isPending}
                  onClick={() => move.mutate(d)}
                  data-testid={`move-to-${d.key}`}
                  className="w-full px-2.5 py-1.5 text-left text-[0.8125rem] text-ink transition hover:bg-sunken disabled:opacity-50"
                >
                  {d.path}
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  )
}

/** Click the title to rename it (spec §4.1). Enter commits, Escape reverts. */
function EditableTitle({ value, onCommit }: {
  value: string
  onCommit: (v: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => setDraft(value), [value])
  useEffect(() => {
    if (editing) inputRef.current?.select()
  }, [editing])

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        data-testid="note-title-input"
        aria-label="Note title"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => { setEditing(false); onCommit(draft.trim()) }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); e.currentTarget.blur() }
          if (e.key === 'Escape') {
            e.preventDefault()
            e.stopPropagation()   // do not also close a modal / the palette
            setDraft(value)
            setEditing(false)
          }
        }}
        className="min-w-0 flex-1 rounded border border-accent bg-surface px-1.5 py-0.5 text-lg font-semibold tracking-tight text-ink outline-none"
      />
    )
  }

  // The Rename control is a sibling of the heading, not a child: the heading
  // should read as exactly the note's title, to a screen reader and to a
  // test alike.
  return (
    <span className="flex items-baseline gap-1.5">
      <h2
        data-testid="note-title"
        onDoubleClick={() => setEditing(true)}
        className="text-lg font-semibold tracking-tight text-ink"
      >
        {value}
      </h2>
      <button
        type="button"
        onClick={() => setEditing(true)}
        aria-label="Rename note"
        data-testid="rename-note"
        className="text-[0.75rem] font-normal text-faint transition hover:text-accent-deep"
      >
        Rename
      </button>
    </span>
  )
}

/** Spec §4.2 — "12 processed · 4 new · 2 edited" in the note header. */
function BlockCounter({ counts }: { counts: Note['counts'] }) {
  return (
    <span data-testid="block-counter" className="text-[0.75rem] tabular-nums text-muted">
      <span className="text-accent-deep">{counts.processed}</span> processed
      <span className="mx-1 text-faint">·</span>
      {counts.new} new
      <span className="mx-1 text-faint">·</span>
      <span className={counts.edited > 0 ? 'text-stale' : undefined}>{counts.edited}</span> edited
    </span>
  )
}

/** Spec §4.1 — "never show a saving spinner that moves layout; use a small
 *  static status dot." Fixed 5rem box so the label never reflows the header. */
function SaveDot({ state }: { state: string }) {
  const label: Record<string, string> = {
    clean: 'Saved', dirty: 'Editing', saving: 'Saving', saved: 'Saved',
    error: 'Retrying',
  }
  const colour: Record<string, string> = {
    clean: 'var(--color-line)',
    dirty: 'var(--color-faint)',
    saving: 'var(--color-accent)',
    saved: 'var(--color-mastery-3)',
    error: 'var(--color-stale)',
  }
  return (
    <span
      data-testid="save-status"
      data-state={state}
      className="flex w-[5rem] shrink-0 items-center justify-end gap-1.5 text-[0.75rem] text-muted"
    >
      <span
        className="size-1.5 rounded-full"
        style={{ background: colour[state] ?? 'var(--color-line)' }}
        aria-hidden="true"
      />
      {label[state] ?? 'Saved'}
    </span>
  )
}

function formatStudyDate(iso: string): string {
  // Parse as a local calendar date; `new Date('YYYY-MM-DD')` is UTC and can
  // render as the previous day west of Greenwich.
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  })
}
