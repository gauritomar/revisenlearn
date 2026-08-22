import { useQuery } from '@tanstack/react-query'
import { api, type AppMeta } from '../lib/api'
import { useUI } from '../store/ui'

/** Spec §14 — right sidebar is contextual and collapsible, state persisted.
 *  In Notes it shows the current resource, pipeline status, concepts extracted
 *  from this note, and related concepts. Those arrive in Phases 2 and 5; the
 *  panel shows the real sections with honest empty states meanwhile. */
export function RightSidebar({ meta }: { meta: AppMeta | undefined }) {
  const noteId = useUI((s) => s.activeNoteId)
  const { data: note } = useQuery({
    queryKey: ['note', noteId],
    queryFn: () => api.note(noteId!),
    enabled: noteId !== null,
  })

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
              <Empty>Not linked to a resource.</Empty>
            </Panel>
            <Panel title="Concepts from this note">
              <Empty>Press Process notes to extract concepts. Arrives in Phase 5.</Empty>
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
            No model is called in Phase 1.
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
