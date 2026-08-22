import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Note } from '../lib/api'
import { useUI } from '../store/ui'

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

  const addNote = useMutation({
    mutationFn: () =>
      api.createNote({
        subtopic_id: note.subtopic_id,
        study_date: note.study_date,
        title: `${note.title} (${siblings.length + 1})`,
      }),
    onSuccess: async (created) => {
      await qc.invalidateQueries({ queryKey: ['notes'] })
      qc.setQueryData(['note', created.id], created)
      openSubtopic(note.subtopic_id ?? -1, created.id)
    },
  })

  const pending = note.counts.new + note.counts.edited

  return (
    <div className="mb-4 border-b border-line-soft pb-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <EditableTitle
          key={note.id}
          value={note.title}
          onCommit={(title) => {
            if (title && title !== note.title) rename.mutate(title)
          }}
        />
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
        {/* Spec §14 — Process notes, showing the unprocessed count. The
            pipeline itself is Phase 5, so the button is present and honest
            rather than absent or fake. */}
        <button
          type="button"
          disabled
          title="The pipeline arrives in Phase 5"
          data-testid="process-notes"
          data-pending={pending}
          className="flex cursor-not-allowed items-center gap-1.5 rounded-md border border-line bg-paper px-2.5 py-1 text-[0.75rem] text-faint"
        >
          Process notes
          {pending > 0 && (
            <span className="rounded bg-sunken px-1.5 py-0.5 text-[0.6875rem] tabular-nums text-muted">
              {pending}
            </span>
          )}
        </button>

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
            <button
              type="button"
              onClick={() => addNote.mutate()}
              disabled={addNote.isPending}
              data-testid="new-note"
              className="rounded-md px-2 py-1 text-[0.75rem] text-muted transition hover:bg-sunken hover:text-ink disabled:opacity-50"
            >
              + New note
            </button>
          </>
        )}
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
