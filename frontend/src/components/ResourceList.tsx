import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { api, type Resource, type ResourceGroup, type ResourceStatus } from '../lib/api'
import { useRefreshEverything } from '../lib/refresh'
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
  const [tagFilter, setTagFilter] = useState<string | null>(null)
  const [addingGroup, setAddingGroup] = useState(false)
  const setResourceAdd = useUI((s) => s.setResourceAdd)
  const refresh = useRefreshEverything()

  const active = FILTERS.find((f) => f.key === filter)
  const { data: resources = [], isLoading } = useQuery({
    queryKey: ['resources', filter, tagFilter],
    queryFn: () => api.resources({
      ...(active?.status ? { status: active.status } : {}),
      ...(tagFilter ? { tag: tagFilter } : {}),
    }),
  })
  const { data: groups = [] } = useQuery({
    queryKey: ['resource-groups'],
    queryFn: api.resourceGroups,
  })
  const { data: tags = [] } = useQuery({ queryKey: ['tags'], queryFn: api.tags })

  const addGroup = useMutation({
    mutationFn: (name: string) => api.createResourceGroup(name),
    onSuccess: async () => { setAddingGroup(false); await refresh() },
  })

  // "Active" is everything still in play — the default view of a to-do list.
  const visible =
    filter === 'active'
      ? resources.filter((r) => !['completed', 'archived'].includes(r.status))
      : resources

  // Filed under their headings, with whatever is unfiled last: a shelf you
  // have not sorted yet is still a shelf.
  const shelves = [
    ...groups.map((group) => ({
      group,
      items: visible.filter((r) => r.group_id === group.id),
    })),
    { group: null, items: visible.filter((r) => r.group_id === null) },
  ].filter((shelf) => shelf.items.length > 0 || shelf.group !== null)

  return (
    <div data-testid="resource-list" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-semibold tracking-tight text-ink">Resources</h2>
        <button
          type="button"
          onClick={() => setAddingGroup(true)}
          data-testid="add-group"
          className="ml-auto rounded-md border border-line px-2.5 py-1.5 text-[0.75rem] text-ink transition hover:border-accent hover:text-accent-deep"
        >
          + Heading
        </button>
        <button
          type="button"
          onClick={() => setResourceAdd(true)}
          data-testid="add-resource"
          className="rounded-md bg-accent px-3 py-1.5 text-[0.8125rem] font-medium text-white transition hover:bg-accent-deep"
        >
          Add resource
        </button>
      </div>

      {addingGroup && (
        <form
          className="mb-3"
          onSubmit={(e) => {
            e.preventDefault()
            const input = e.currentTarget.elements.namedItem('name') as HTMLInputElement
            if (input.value.trim()) addGroup.mutate(input.value.trim())
          }}
        >
          <input
            name="name"
            autoFocus
            data-testid="new-group-name"
            placeholder="Heading — Interview prep, Courses, Papers…"
            onKeyDown={(e) => { if (e.key === 'Escape') setAddingGroup(false) }}
            onBlur={(e) => { if (!e.currentTarget.value.trim()) setAddingGroup(false) }}
            className="w-full rounded-md border border-accent bg-surface px-2.5 py-1.5 text-[0.8125rem] text-ink outline-none"
          />
        </form>
      )}

      <div className="mb-3 flex flex-wrap gap-1">
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

      {/* Tags cut across headings — that is what they are for, so they filter
          the whole library rather than one shelf. */}
      {tags.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-1" data-testid="tag-filters">
          {tags.map((tag) => (
            <button
              key={tag.id}
              type="button"
              onClick={() => setTagFilter(tagFilter === tag.name ? null : tag.name)}
              data-testid={`tag-filter-${tag.name}`}
              className={[
                'rounded-full border px-2 py-0.5 text-[0.6875rem] transition',
                tagFilter === tag.name
                  ? 'border-accent bg-accent-wash text-accent-deep'
                  : 'border-line text-muted hover:border-faint hover:text-ink',
              ].join(' ')}
            >
              {tag.name}
            </button>
          ))}
          {tagFilter && (
            <button
              type="button"
              onClick={() => setTagFilter(null)}
              className="px-1.5 text-[0.6875rem] text-faint transition hover:text-ink"
            >
              clear
            </button>
          )}
        </div>
      )}

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
        <div className="space-y-5">
          {shelves.map((shelf) => (
            <Shelf
              key={shelf.group?.id ?? 'ungrouped'}
              group={shelf.group}
              items={shelf.items}
              groups={groups}
              onChanged={refresh}
            />
          ))}
        </div>
      )}
    </div>
  )
}

/** One heading and what is filed under it. */
function Shelf({ group, items, groups, onChanged }: {
  group: ResourceGroup | null
  items: Resource[]
  groups: ResourceGroup[]
  onChanged: () => void | Promise<void>
}) {
  const openResource = useUI((s) => s.openResource)

  const removeGroup = useMutation({
    mutationFn: () => api.deleteResourceGroup(group!.id),
    onSuccess: onChanged,
  })

  return (
    <section data-testid={`shelf-${group?.id ?? 'ungrouped'}`}>
      <div className="group mb-1.5 flex items-baseline gap-2">
        <h3 className="text-[0.75rem] font-semibold uppercase tracking-[0.09em] text-muted">
          {group?.name ?? 'Unfiled'}
        </h3>
        <span className="text-[0.6875rem] tabular-nums text-faint">{items.length}</span>
        {group && (
          <button
            type="button"
            onClick={() => removeGroup.mutate()}
            data-testid={`delete-group-${group.id}`}
            title="Delete this heading — the resources under it stay"
            className="ml-auto text-[0.6875rem] text-faint opacity-0 transition hover:text-stale focus-visible:opacity-100 group-hover:opacity-100"
          >
            remove heading
          </button>
        )}
      </div>

      {items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line-soft px-3 py-4 text-center text-[0.75rem] text-faint">
          Nothing filed here yet.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((r) => (
            <li key={r.id}>
              <div className="rounded-lg border border-line bg-surface p-3 transition hover:border-faint">
                <button
                  type="button"
                  onClick={() => openResource(r.id)}
                  data-testid={`resource-${r.id}`}
                  className="w-full text-left"
                >
                  <ResourceRow resource={r} />
                </button>
                <ResourceTags resource={r} groups={groups} onChanged={onChanged} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** Tags on one resource, and the heading it is filed under. */
function ResourceTags({ resource, groups, onChanged }: {
  resource: Resource
  groups: ResourceGroup[]
  onChanged: () => void | Promise<void>
}) {
  const [adding, setAdding] = useState(false)

  const tag = useMutation({
    mutationFn: (name: string) => api.tagResource(resource.id, name),
    onSuccess: async () => { setAdding(false); await onChanged() },
  })
  const untag = useMutation({
    mutationFn: (tagId: number) => api.untagResource(resource.id, tagId),
    onSuccess: onChanged,
  })
  const file = useMutation({
    mutationFn: (groupId: number | null) =>
      api.updateResource(resource.id, { group_id: groupId }),
    onSuccess: onChanged,
  })

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1">
      {resource.tags.map((t) => (
        <span
          key={t.id}
          data-testid={`resource-${resource.id}-tag-${t.name}`}
          className="flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[0.6875rem] text-muted"
        >
          {t.name}
          <button
            type="button"
            onClick={() => untag.mutate(t.id)}
            aria-label={`Remove tag ${t.name}`}
            className="text-faint transition hover:text-stale"
          >
            ×
          </button>
        </span>
      ))}

      {adding ? (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            const input = e.currentTarget.elements.namedItem('tag') as HTMLInputElement
            if (input.value.trim()) tag.mutate(input.value.trim())
          }}
        >
          <input
            name="tag"
            autoFocus
            data-testid={`tag-input-${resource.id}`}
            placeholder="tag…"
            onKeyDown={(e) => { if (e.key === 'Escape') setAdding(false) }}
            onBlur={(e) => { if (!e.currentTarget.value.trim()) setAdding(false) }}
            className="w-24 rounded-full border border-accent bg-surface px-2 py-0.5 text-[0.6875rem] text-ink outline-none"
          />
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          data-testid={`add-tag-${resource.id}`}
          className="rounded-full border border-dashed border-line px-2 py-0.5 text-[0.6875rem] text-faint transition hover:border-accent hover:text-accent-deep"
        >
          + tag
        </button>
      )}

      {groups.length > 0 && (
        <select
          value={resource.group_id ?? ''}
          onChange={(e) => file.mutate(e.target.value ? Number(e.target.value) : null)}
          data-testid={`file-${resource.id}`}
          aria-label={`File ${resource.title} under a heading`}
          className="ml-auto rounded border border-line bg-paper px-1.5 py-0.5 text-[0.6875rem] text-muted"
        >
          <option value="">Unfiled</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>{g.name}</option>
          ))}
        </select>
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
