import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type AppMeta, type NotePanel, type PipelineJob } from '../lib/api'
import { useUI, type RightTab } from '../store/ui'
import { StatusPill } from './ResourceList'

/** Spec §14 — the right sidebar is contextual and collapsible, state
 *  persisted.
 *
 *  Consolidated addendum §6 makes it **tabbed** rather than a fixed stack:
 *  Checklist (default whenever the lesson has items), Pipeline & Concepts,
 *  Resources. The pipeline tab "gets a small badge when a job finishes while
 *  the user has Checklist open — never force-switches the tab away from what
 *  they're doing."
 */
const ACTIVE = new Set(['queued', 'running'])

export function RightSidebar({ meta }: { meta: AppMeta | undefined }) {
  const noteId = useUI((s) => s.activeNoteId)
  const resourceId = useUI((s) => s.activeResourceId)
  const tab = useUI((s) => s.rightTab)
  const setTab = useUI((s) => s.setRightTab)
  const badge = useUI((s) => s.pipelineBadge)
  const setBadge = useUI((s) => s.setPipelineBadge)

  const { data: resourceNote } = useQuery({
    queryKey: ['resource-note', resourceId],
    queryFn: () => api.ensureResourceNote(resourceId!),
    enabled: resourceId !== null,
  })

  const openNoteId = resourceId !== null ? (resourceNote?.id ?? null) : noteId

  const { data: panel } = useQuery({
    queryKey: ['note-panel', openNoteId],
    queryFn: () => api.notePanel(openNoteId!),
    enabled: openNoteId !== null,
  })

  const { data: jobs = [] } = useQuery({
    queryKey: ['pipeline-jobs'],
    queryFn: api.jobs,
    refetchInterval: (query) =>
      (query.state.data ?? []).some((j: PipelineJob) => ACTIVE.has(j.status)) ? 1000 : false,
  })
  const running = jobs.find((j) => ACTIVE.has(j.status))
  const latest = jobs[0]

  // §6 — a job finishing raises a badge, and nothing else. The tab the user
  // chose stays put.
  useEffect(() => {
    if (running || !latest || latest.status !== 'succeeded') return
    if (useUI.getState().rightTab !== 'pipeline') setBadge(true)
  }, [running, latest?.id, latest?.status, setBadge])

  // §6.1 — Checklist is the default "whenever the lesson has checklist
  // items", which includes the moment the first one is typed. But a tab the
  // user picked themselves is never overridden: §6 is explicit that this
  // panel must not switch away from what they are doing. So the default
  // applies only until they choose, and choosing is remembered per note.
  const chosenFor = useRef<number | null>(null)
  useEffect(() => {
    if (!panel || chosenFor.current === panel.note_id) return
    setTab(panel.counts.checklist > 0 ? 'checklist' : 'pipeline')
  }, [panel, setTab])

  const chooseTab = (next: RightTab) => {
    if (panel) chosenFor.current = panel.note_id
    setTab(next)
  }

  const tabs: Array<{ key: RightTab; label: string; count?: number; dot?: boolean }> = [
    { key: 'checklist', label: 'Checklist', count: panel?.counts.checklist },
    { key: 'pipeline', label: 'Pipeline', dot: badge },
    { key: 'resources', label: 'Links', count: panel?.counts.resources },
  ]

  return (
    <aside
      data-testid="right-sidebar"
      className="flex h-full w-64 shrink-0 flex-col border-l border-line bg-paper"
    >
      {openNoteId === null ? (
        <>
          <PanelHeader>Context</PanelHeader>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
            <Panel title="Getting started">
              <Empty>
                Open a lesson on the left to write against it, or press
                &#8984;K to search.
              </Empty>
            </Panel>
            <StatusPanel meta={meta} />
          </div>
        </>
      ) : (
        <>
          <div
            role="tablist"
            aria-label="Note panel"
            data-testid="right-tabs"
            className="flex h-11 shrink-0 items-stretch border-b border-line-soft"
          >
            {tabs.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                onClick={() => chooseTab(t.key)}
                data-testid={`right-tab-${t.key}`}
                className={[
                  'relative flex flex-1 items-center justify-center gap-1 text-[0.75rem] transition',
                  tab === t.key
                    ? 'border-b-2 border-accent font-medium text-accent-deep'
                    : 'border-b-2 border-transparent text-muted hover:text-ink',
                ].join(' ')}
              >
                {t.label}
                {t.count ? (
                  <span className="text-[0.625rem] tabular-nums text-faint">{t.count}</span>
                ) : null}
                {t.dot && (
                  <span
                    data-testid="pipeline-badge"
                    aria-label="A job finished"
                    className="absolute right-2 top-2.5 size-1.5 rounded-full bg-accent"
                  />
                )}
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
            {tab === 'checklist' && <ChecklistTab noteId={openNoteId} panel={panel} />}
            {tab === 'pipeline' && (
              <PipelineTab panel={panel} running={running} latest={latest} meta={meta} />
            )}
            {tab === 'resources' && <ResourcesTab panel={panel} />}
          </div>
        </>
      )}
    </aside>
  )
}

// --------------------------------------------------------------------------
// Tabs
// --------------------------------------------------------------------------

/** §6.1 — "live list of this lesson's `checklist_items`, click to toggle
 *  (writes through to the note block, per §2). Small inline "+ add item"
 *  appends a new checklist block to the note without breaking writing flow." */
function ChecklistTab({ noteId, panel }: {
  noteId: number
  panel: NotePanel | undefined
}) {
  const qc = useQueryClient()

  const invalidate = async () => {
    await qc.invalidateQueries({ queryKey: ['note-panel', noteId] })
    await qc.invalidateQueries({ queryKey: ['note', noteId] })
    await qc.invalidateQueries({ queryKey: ['subjects'] })
    await qc.invalidateQueries({ queryKey: ['roadmap'] })
  }

  const toggle = useMutation({
    mutationFn: ({ id, checked }: { id: number; checked: boolean }) =>
      api.toggleChecklistItem(id, checked),
    onSuccess: invalidate,
  })

  const add = useMutation({
    mutationFn: async (text: string) => {
      // Appended as a real block, because that is the only place a checklist
      // item exists (§2). The projection follows on save.
      const note = await api.note(noteId)
      const blocks = note.blocks.map((b) => ({
        id: b.id, position: b.position, block_type: b.block_type, text: b.text,
      }))
      blocks.push({
        id: null as unknown as number,
        position: blocks.length,
        block_type: 'checklist_item',
        text: `- [ ] ${text}`,
      })
      return api.saveBlocks(noteId, blocks)
    },
    onSuccess: invalidate,
  })

  if (!panel) return <Empty>Loading…</Empty>

  return (
    <section data-testid="checklist-tab">
      {panel.checklist.length === 0 ? (
        <Empty>
          No checklist here yet. Type <span className="text-muted">- [ ]</span> in
          the note, or add one below.
        </Empty>
      ) : (
        <ul className="space-y-0.5">
          {panel.checklist.map((item) => (
            <li
              key={item.id}
              className={[
                'flex items-baseline gap-2 rounded px-1 py-1 transition hover:bg-sunken',
                item.parent_checklist_item_id ? 'ml-4' : '',
              ].join(' ')}
            >
              <input
                type="checkbox"
                checked={item.checked}
                onChange={(e) => toggle.mutate({ id: item.id, checked: e.target.checked })}
                data-testid={`panel-item-${item.id}`}
                className="size-3.5 shrink-0 accent-[var(--color-accent)]"
              />
              <span
                className={`min-w-0 flex-1 text-[0.8125rem] leading-snug ${
                  item.checked ? 'text-faint line-through' : 'text-ink-soft'
                }`}
              >
                {item.text}
              </span>
            </li>
          ))}
        </ul>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault()
          const input = e.currentTarget.elements.namedItem('item') as HTMLInputElement
          const text = input.value.trim()
          if (!text) return
          add.mutate(text)
          input.value = ''
        }}
        className="mt-2"
      >
        <input
          name="item"
          data-testid="panel-add-item"
          placeholder="+ add item"
          className="w-full rounded-md border border-transparent bg-transparent px-1.5 py-1 text-[0.8125rem] text-ink outline-none transition placeholder:text-faint hover:border-line focus:border-accent focus:bg-surface"
        />
      </form>
    </section>
  )
}

/** §6.2 — job status, concepts extracted, related concepts. */
function PipelineTab({ panel, running, latest, meta }: {
  panel: NotePanel | undefined
  running: PipelineJob | undefined
  latest: PipelineJob | undefined
  meta: AppMeta | undefined
}) {
  return (
    <div data-testid="pipeline-tab" className="space-y-4">
      <Panel title="Pipeline">
        {running ? (
          <p className="flex items-center gap-2 text-[0.8125rem] text-ink-soft">
            <span className="size-1.5 animate-pulse rounded-full bg-accent" aria-hidden="true" />
            {running.stage ?? 'queued'}
          </p>
        ) : latest ? (
          <dl className="space-y-1 text-[0.8125rem]">
            <Row label="Last run" value={latest.status} />
            <Row label="Blocks" value={latest.block_count ?? '—'} />
          </dl>
        ) : (
          <Empty>No job has run yet. Press Process notes when you are ready.</Empty>
        )}
      </Panel>

      <Panel title="Concepts from this note">
        {!panel || panel.concepts.length === 0 ? (
          <Empty>Nothing extracted yet.</Empty>
        ) : (
          <ul className="space-y-1.5" data-testid="panel-concepts">
            {panel.concepts.map((concept) => (
              <li key={concept.id}>
                <p className="text-[0.8125rem] font-medium leading-snug text-ink">
                  {concept.name}
                </p>
                {concept.definition && (
                  <p className="text-[0.75rem] leading-snug text-muted">
                    {concept.definition}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Related concepts">
        {!panel || panel.related.length === 0 ? (
          <Empty>Nothing connected yet.</Empty>
        ) : (
          <ul className="space-y-1" data-testid="panel-related">
            {panel.related.map((concept) => (
              <li key={concept.id} className="flex items-baseline gap-2 text-[0.8125rem]">
                <span className="min-w-0 flex-1 truncate text-ink-soft">{concept.name}</span>
                <span className="shrink-0 text-[0.625rem] uppercase tracking-wide text-faint">
                  {concept.relation}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <StatusPanel meta={meta} />
    </div>
  )
}

/** §6.3 — "links referenced in this note (from §4's auto-detection),
 *  quick-clickable." */
function ResourcesTab({ panel }: { panel: NotePanel | undefined }) {
  const openResource = useUI((s) => s.openResource)

  if (!panel || panel.resources.length === 0) {
    return (
      <Empty>
        No links here yet. Paste a URL into the note and it becomes a resource
        on its own.
      </Empty>
    )
  }

  return (
    <ul className="space-y-1.5" data-testid="resources-tab">
      {panel.resources.map((resource) => (
        <li key={resource.id}>
          <button
            type="button"
            onClick={() => openResource(resource.id)}
            data-testid={
              // Spec §14 — the note's own resource is "the current resource".
              resource.is_current ? 'sidebar-resource' : `panel-resource-${resource.id}`
            }
            className={[
              'w-full rounded-md border bg-surface p-2 text-left transition',
              resource.is_current ? 'border-accent' : 'border-line hover:border-faint',
            ].join(' ')}
          >
            <p className="truncate text-[0.8125rem] font-medium leading-snug text-ink">
              {resource.title}
            </p>
            <span className="mt-1 flex items-center gap-2">
              <StatusPill status={resource.status} />
              <span className="text-[0.6875rem] tabular-nums text-faint">
                {resource.progress_pct}%
              </span>
            </span>
            {resource.progress_note && (
              <p className="mt-1 text-[0.75rem] leading-snug text-muted">
                {resource.progress_note}
              </p>
            )}
          </button>
        </li>
      ))}
    </ul>
  )
}

// --------------------------------------------------------------------------

function StatusPanel({ meta }: { meta: AppMeta | undefined }) {
  return (
    <Panel title="Status">
      <dl className="space-y-1 text-[0.8125rem]">
        <Row label="Version" value={meta?.version ?? '—'} />
        <Row
          label="API key"
          value={meta?.api_key.present ? meta.api_key.source : 'absent'}
        />
      </dl>
    </Panel>
  )
}

function PanelHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-11 shrink-0 items-center border-b border-line-soft px-3">
      <span className="text-[0.6875rem] font-semibold uppercase tracking-[0.09em] text-muted">
        {children}
      </span>
    </div>
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