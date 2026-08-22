import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api, type Resource, type ResourceStatus } from '../lib/api'
import { useUI } from '../store/ui'

/** Spec §5 — the to-do list. Statuses flow inbox → next → in_progress →
 *  completed → archived. */
const FILTERS: Array<{ key: string; label: string; status?: ResourceStatus }> = [
  { key: 'active', label: 'Active' },
  { key: 'inbox', label: 'Inbox', status: 'inbox' },
  { key: 'next', label: 'Next', status: 'next' },
  { key: 'in_progress', label: 'In progress', status: 'in_progress' },
  { key: 'completed', label: 'Completed', status: 'completed' },
]

export function ResourceList() {
  const [filter, setFilter] = useState('active')
  const setResourceAdd = useUI((s) => s.setResourceAdd)
  const openResource = useUI((s) => s.openResource)

  const active = FILTERS.find((f) => f.key === filter)
  const { data: resources = [], isLoading } = useQuery({
    queryKey: ['resources', filter],
    queryFn: () => api.resources(active?.status ? { status: active.status } : {}),
  })

  // "Active" is everything still in play — the default view of a to-do list.
  const visible =
    filter === 'active'
      ? resources.filter((r) => !['completed', 'archived'].includes(r.status))
      : resources

  return (
    <div data-testid="resource-list" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-semibold tracking-tight text-ink">Resources</h2>
        <button
          type="button"
          onClick={() => setResourceAdd(true)}
          data-testid="add-resource"
          className="ml-auto rounded-md bg-accent px-3 py-1.5 text-[0.8125rem] font-medium text-white transition hover:bg-accent-deep"
        >
          Add resource
        </button>
      </div>

      <div className="mb-4 flex flex-wrap gap-1">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            data-testid={`filter-${f.key}`}
            className={[
              'rounded-md px-2.5 py-1 text-[0.75rem] transition',
              filter === f.key
                ? 'bg-accent-wash font-medium text-accent-deep'
                : 'text-muted hover:bg-sunken hover:text-ink',
            ].join(' ')}
          >
            {f.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <p className="text-[0.8125rem] text-faint">Loading…</p>
      ) : visible.length === 0 ? (
        <button
          type="button"
          onClick={() => setResourceAdd(true)}
          data-testid="resource-list-empty"
          className="w-full rounded-lg border border-dashed border-line bg-surface px-4 py-10 text-center text-[0.875rem] text-muted transition hover:border-accent hover:text-accent-deep"
        >
          Nothing here. Paste a link to add your first resource.
        </button>
      ) : (
        <ul className="space-y-1.5">
          {visible.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => openResource(r.id)}
                data-testid={`resource-${r.id}`}
                className="w-full rounded-lg border border-line bg-surface p-3 text-left transition hover:border-faint"
              >
                <ResourceRow resource={r} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

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
