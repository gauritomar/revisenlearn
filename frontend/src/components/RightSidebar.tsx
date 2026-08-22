import { useQuery } from '@tanstack/react-query'

import { api, type AppMeta } from '../lib/api'
import { useUI } from '../store/ui'
import { StatusPill } from './ResourceList'

/** Spec §14 — right sidebar is contextual and collapsible, state persisted.
 *  In Notes it shows the current resource, pipeline status, concepts extracted
 *  from this note, and related concepts. Concepts arrive in Phase 5; those
 *  panels name what will fill them rather than pretending to be empty.
 */
export function RightSidebar({ meta }: { meta: AppMeta | undefined }) {
  const noteId = useUI((s) => s.activeNoteId)
  const resourceId = useUI((s) => s.activeResourceId)

  const { data: resource } = useQuery({
    queryKey: ['resource', resourceId],
    queryFn: () => api.resource(resourceId!),
    enabled: resourceId !== null,
  })

  // In a resource split view the open note is the resource's own note, which
  // the split view fetched under a different key.
  const { data: resourceNote } = useQuery({
    queryKey: ['resource-note', resourceId],
    queryFn: () => api.ensureResourceNote(resourceId!),
    enabled: resourceId !== null,
  })

  const { data: subtopicNote } = useQuery({
    queryKey: ['note', noteId],
    queryFn: () => api.note(noteId!),
    enabled: noteId !== null,
  })

  const note = resourceId !== null ? resourceNote : subtopicNote

  return (
    <aside
      data-testid="right-sidebar"
      className="flex h-full w-64 shrink-0 flex-col border-l border-line bg-paper"
    >
      <div className="flex h-11 shrink-0 items-center border-b border-line-soft px-3">
        <span className="text-[0.6875rem] font-semibold uppercase tracking-[0.09em] text-muted">
          {note ? 'This note' : 'Context'}
        </span>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
        {note ? (
          <>
            <Panel title="Blocks">
              <dl className="space-y-1 text-[0.8125rem]">
                <Row label="Processed" value={note.counts.processed} />
                <Row label="New" value={note.counts.new} />
                <Row label="Edited" value={note.counts.edited} />
              </dl>
            </Panel>

            <Panel title="Resource">
              {resource ? (
                <div data-testid="sidebar-resource">
                  <p className="text-[0.8125rem] font-medium leading-snug text-ink">
                    {resource.title}
                  </p>
                  <div className="mt-1.5 flex items-center gap-2">
                    <StatusPill status={resource.status} />
                    <span className="text-[0.6875rem] tabular-nums text-faint">
                      {resource.progress_pct}%
                    </span>
                  </div>
                  {resource.progress_note && (
                    <p className="mt-1 text-[0.75rem] leading-snug text-muted">
                      {resource.progress_note}
                    </p>
                  )}
                </div>
              ) : (
                <Empty>Not linked to a resource.</Empty>
              )}
            </Panel>

            <Panel title="Pipeline">
              <Empty>No job has run. Arrives in Phase 5.</Empty>
            </Panel>

            <Panel title="Concepts from this note">
              <Empty>Press Process notes to extract concepts. Arrives in Phase 5.</Empty>
            </Panel>

            <Panel title="Related concepts">
              <Empty>Needs the graph. Arrives in Phase 8.</Empty>
            </Panel>
          </>
        ) : (
          <Panel title="Getting started">
            <Empty>
              Pick a subtopic on the left to open today&rsquo;s note, or press
              &#8984;K to search.
            </Empty>
          </Panel>
        )}

        <Panel title="Status">
          <dl className="space-y-1 text-[0.8125rem]">
            <Row label="Phase" value={meta?.phase ?? '—'} />
            <Row label="Version" value={meta?.version ?? '—'} />
            <Row
              label="API key"
              value={meta?.api_key.present ? meta.api_key.source : 'absent'}
            />
          </dl>
          <p className="mt-2 text-[0.75rem] leading-relaxed text-faint">
            No model is called yet.
          </p>
        </Panel>
      </div>
    </aside>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-surface p-3">
      <h3 className="mb-2 text-[0.75rem] font-semibold tracking-tight text-ink">{title}</h3>
      {children}
    </section>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-muted">{label}</dt>
      <dd className="truncate tabular-nums text-ink">{value}</dd>
    </div>
  )
}

const Empty = ({ children }: { children: React.ReactNode }) => (
  <p className="text-[0.8125rem] leading-relaxed text-faint">{children}</p>
)
