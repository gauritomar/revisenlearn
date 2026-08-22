import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Resource, type ResourceStatus } from '../lib/api'
import { useUI } from '../store/ui'
import { NoteEditor } from './NoteEditor'

/** Spec §5.1 — clicking a resource opens a split view:
 *  left  = metadata, status control, progress slider, "Open link"
 *  right = the note for that resource + today's date, created on the spot.
 *
 *  §14.1 stacks it single-column below 900px, where the note comes first —
 *  the editor is always the dominant element.
 */
const STATUSES: ResourceStatus[] = ['inbox', 'next', 'in_progress', 'completed', 'archived']

const STATUS_LABEL: Record<ResourceStatus, string> = {
  inbox: 'Inbox',
  next: 'Next',
  in_progress: 'In progress',
  completed: 'Completed',
  archived: 'Archived',
}

export function ResourceSplitView({ resourceId }: { resourceId: number }) {
  const qc = useQueryClient()
  const clearResource = useUI((s) => s.clearResource)

  const { data: resource } = useQuery({
    queryKey: ['resource', resourceId],
    queryFn: () => api.resource(resourceId),
  })
  const { data: note } = useQuery({
    queryKey: ['resource-note', resourceId],
    queryFn: () => api.ensureResourceNote(resourceId),
  })

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.updateResource(resourceId, body),
    onSuccess: (updated) => {
      qc.setQueryData(['resource', resourceId], updated)
      void qc.invalidateQueries({ queryKey: ['resources'] })
      void qc.invalidateQueries({ queryKey: ['study-next'] })
    },
  })

  const openLink = useMutation({
    mutationFn: () => api.openResource(resourceId),
    onSuccess: (updated) => qc.setQueryData(['resource', resourceId], updated),
  })

  if (!resource) {
    return <div className="p-6 text-[0.8125rem] text-faint">Opening resource…</div>
  }

  return (
    <div
      data-testid="resource-split"
      className="flex h-full min-h-0 flex-col-reverse lg:flex-row"
    >
      {/* Left: the resource itself */}
      <div className="shrink-0 overflow-y-auto border-line lg:w-72 lg:border-r">
        <div className="space-y-4 border-t border-line p-4 lg:border-t-0">
          <div>
            <button
              type="button"
              onClick={clearResource}
              className="mb-2 flex items-center gap-1 text-[0.75rem] text-muted transition hover:text-ink"
            >
              <span aria-hidden="true">&larr;</span> All resources
            </button>
            <h2 data-testid="resource-title" className="text-[0.9375rem] font-semibold leading-snug text-ink">
              {resource.title}
            </h2>
            <p className="mt-1 text-[0.75rem] text-faint">
              {resource.resource_type.replace(/_/g, ' ')}
            </p>
          </div>

          {resource.url && (
            <button
              type="button"
              onClick={() => openLink.mutate()}
              data-testid="open-link"
              className="w-full rounded-md bg-accent px-3 py-2 text-[0.8125rem] font-medium text-white transition hover:bg-accent-deep"
            >
              Open link
            </button>
          )}

          <Field label="Status">
            <select
              value={resource.status}
              data-testid="resource-status"
              onChange={(e) => patch.mutate({ status: e.target.value })}
              className="w-full rounded-md border border-line bg-paper px-2 py-1.5 text-[0.8125rem] text-ink outline-none transition focus:border-accent focus:bg-surface"
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>{STATUS_LABEL[s]}</option>
              ))}
            </select>
          </Field>

          <ProgressControl resource={resource} onCommit={(body) => patch.mutate(body)} />

          {resource.last_opened_at && (
            <p className="text-[0.6875rem] text-faint">
              Last opened {new Date(resource.last_opened_at).toLocaleString()}
            </p>
          )}
        </div>
      </div>

      {/* Right: today's note for this resource */}
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        {note ? (
          <NoteEditor noteId={note.id} />
        ) : (
          <div className="p-6 text-[0.8125rem] text-faint">Opening today&rsquo;s note…</div>
        )}
      </div>
    </div>
  )
}

/** Spec §5 — progress is an integer 0–100 the user sets manually with a
 *  slider, plus a free-text note. Never computed.
 *
 *  The slider is local while dragging and only commits on release, so a drag
 *  is one write rather than eighty. */
function ProgressControl({ resource, onCommit }: {
  resource: Resource
  onCommit: (body: Record<string, unknown>) => void
}) {
  const [pct, setPct] = useState(resource.progress_pct)
  const [noteText, setNoteText] = useState(resource.progress_note ?? '')
  const dragging = useRef(false)

  // Adopt server values unless the user is mid-drag.
  useEffect(() => {
    if (!dragging.current) setPct(resource.progress_pct)
  }, [resource.progress_pct])
  useEffect(() => {
    setNoteText(resource.progress_note ?? '')
  }, [resource.progress_note])

  return (
    <Field label={`Progress — ${pct}%`}>
      <input
        type="range"
        min={0}
        max={100}
        step={1}
        value={pct}
        data-testid="progress-slider"
        aria-label="Progress percent"
        onPointerDown={() => { dragging.current = true }}
        onChange={(e) => setPct(Number(e.target.value))}
        onPointerUp={() => { dragging.current = false; onCommit({ progress_pct: pct }) }}
        onKeyUp={() => onCommit({ progress_pct: pct })}
        className="w-full accent-[var(--color-accent)]"
      />
      <input
        value={noteText}
        placeholder="stopped at chapter 4"
        data-testid="progress-note"
        aria-label="Progress note"
        onChange={(e) => setNoteText(e.target.value)}
        onBlur={() => {
          if (noteText !== (resource.progress_note ?? '')) {
            onCommit({ progress_note: noteText })
          }
        }}
        className="mt-2 w-full rounded-md border border-line bg-paper px-2 py-1.5 text-[0.8125rem] text-ink outline-none transition placeholder:text-faint focus:border-accent focus:bg-surface"
      />
    </Field>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[0.6875rem] font-medium text-ink-soft">{label}</span>
      {children}
    </label>
  )
}
