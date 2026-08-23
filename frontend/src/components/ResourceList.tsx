import { useQuery } from '@tanstack/react-query'

import { api, type Resource, type ResourceStatus } from '../lib/api'
import { NoteEditor } from './NoteEditor'

/** Resources — a page to write on.
 *
 *  "Just a place to write a note but obviously it is not to be tested on,
 *  just a blank page to write and save resources I want to work on later."
 *
 *  It was a filing system: statuses, headings, tags, filters, progress bars.
 *  None of that is what saving a link is. This is the note, and nothing else:
 *  bullets, headings, code fences, all the same keys as any other page. Its
 *  blocks are never sent to the model and never count as a day's study —
 *  a reading list is not something to be examined on.
 *
 *  The Resource *records* still exist behind the scenes: a URL written in a
 *  study note is still detected (§4), the split view still opens against one,
 *  and the dashboard still ranks what to study next. This screen simply
 *  stopped being their filing cabinet.
 */
export function ResourceList() {
  const { data: note, isLoading } = useQuery({
    queryKey: ['scratch', 'resources'],
    queryFn: () => api.scratchNote('resources'),
  })

  if (isLoading || !note) {
    return <div className="p-6 text-[0.8125rem] text-faint">Opening…</div>
  }

  return (
    <div
      data-testid="resource-list"
      className="mx-auto flex h-full w-full max-w-3xl flex-col px-4 py-5 sm:px-6"
    >
      <p className="mb-1 text-[0.75rem] text-faint">
        Anything you want to come back to. Not processed, not tested on.
      </p>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <NoteEditor noteId={note.id} titleOverride="Resources" />
      </div>
    </div>
  )
}

/** Still used by the dashboard and the split view, which show one resource
 *  at a time rather than a library. */
export function ResourceRow({ resource }: { resource: Resource }) {
  return (
    <>
      <div className="flex items-baseline gap-2">
        <span className="min-w-0 flex-1 truncate text-[0.875rem] font-medium text-ink">
          {resource.title}
        </span>
        <StatusPill status={resource.status} />
      </div>
      <div className="mt-1.5 flex items-center gap-2">
        <div
          className="h-1 min-w-0 flex-1 overflow-hidden rounded-full bg-sunken"
          role="progressbar"
          aria-valuenow={resource.progress_pct}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full rounded-full bg-accent transition-[width]"
            style={{ width: `${resource.progress_pct}%` }}
          />
        </div>
        <span className="shrink-0 text-[0.6875rem] tabular-nums text-faint">
          {resource.progress_pct}%
        </span>
      </div>
      {resource.progress_note && (
        <p className="mt-1 truncate text-[0.75rem] text-muted">{resource.progress_note}</p>
      )}
    </>
  )
}

export function StatusPill({ status }: { status: ResourceStatus }) {
  const tone: Record<ResourceStatus, string> = {
    inbox: 'bg-sunken text-muted',
    next: 'bg-accent-wash text-accent-deep',
    in_progress: 'bg-accent-wash text-accent-deep',
    completed: 'bg-sunken text-mastery-3',
    archived: 'bg-sunken text-faint',
  }
  return (
    <span
      className={`shrink-0 rounded px-1.5 py-0.5 text-[0.625rem] uppercase tracking-wide ${tone[status]}`}
    >
      {status.replace(/_/g, ' ')}
    </span>
  )
}
