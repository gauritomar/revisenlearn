import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import cytoscape from 'cytoscape'
import coseBilkent from 'cytoscape-cose-bilkent'

import {
  api,
  type ConceptRow,
  type GraphPayload,
  type MergeRow,
  type ProposedEdge,
} from '../lib/api'

cytoscape.use(coseBilkent)

/** The Knowledge Graph console (spec §13 **[LOCKED]**).
 *
 *  "This is a curation workspace, not a decoration. Two panes: the graph on the
 *  left, a work queue on the right."
 *
 *  §13.1 fixes the styling: nodes coloured by mastery badge state, sized by
 *  importance; edges styled by relation_type and dashed when proposed. These
 *  are the only place mastery colours appear outside the concept side — the
 *  addendum's §5 reserves them, and the progress bars in Roadmap deliberately
 *  do not use them.
 */
const BADGE_COLOUR: Record<string, string> = {
  mastered: '#47704A',
  fading: '#D9A05B',
  learning: '#6B6BDC',
  untested: '#C8C2B8',
}

const RELATION_COLOUR: Record<string, string> = {
  prerequisite_of: '#4F4FC4',
  depends_on: '#6B6BDC',
  part_of: '#7A736A',
  related_to: '#A9A198',
  contrasts_with: '#D9A05B',
  causes: '#C2903F',
}

const VIEWS: Array<{ key: string; label: string }> = [
  { key: 'entire_graph', label: 'Entire graph' },
  { key: 'weak_concepts', label: 'Weak concepts' },
  { key: 'orphans', label: 'Orphan nodes' },
  { key: 'missing_prerequisites', label: 'Missing prerequisites' },
  { key: 'stale_concepts', label: 'Stale concepts' },
]

const TABS = [
  { key: 'merge_queue', label: 'Merge queue' },
  { key: 'proposed_edges', label: 'Proposed edges' },
  { key: 'stale_concepts', label: 'Stale' },
  { key: 'auto_merged', label: 'Auto-merged' },
  { key: 'orphans', label: 'Orphans' },
] as const

export function Graph() {
  const [view, setView] = useState('entire_graph')
  const [search, setSearch] = useState('')
  const [subjectId, setSubjectId] = useState<number | ''>('')
  const [mastery, setMastery] = useState('')
  const [jobId, setJobId] = useState<number | ''>('')
  const [selected, setSelected] = useState<number | null>(null)
  const [tab, setTab] = useState<(typeof TABS)[number]['key']>('merge_queue')

  const { data: subjects = [] } = useQuery({ queryKey: ['subjects'], queryFn: api.subjects })
  const { data: jobs = [] } = useQuery({ queryKey: ['pipeline-jobs'], queryFn: api.jobs })
  const { data: counts } = useQuery({ queryKey: ['graph-queues'], queryFn: api.graphQueues })

  const { data: graph } = useQuery({
    queryKey: ['graph', view, search, subjectId, mastery, jobId, selected],
    queryFn: () =>
      api.graph({
        view,
        ...(search ? { search } : {}),
        ...(subjectId === '' ? {} : { subject_id: subjectId }),
        ...(mastery ? { mastery } : {}),
        ...(jobId === '' ? {} : { job_id: jobId }),
        ...(view === 'neighbourhood' && selected ? { concept_id: selected } : {}),
      }),
  })

  return (
    // `h-full` cannot resolve inside the scrolling <main>, which has no
    // definite height, so the Cytoscape container would collapse to zero and
    // never paint. The header is 3.5rem; take the rest of the viewport.
    <div
      data-testid="graph-console"
      className="flex min-h-0 flex-col lg:h-[calc(100vh-3.5rem)] lg:flex-row"
    >
      {/* Left: the graph */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col border-line lg:border-r">
        <div className="flex flex-wrap items-center gap-1.5 border-b border-line-soft p-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search concepts"
            data-testid="graph-search"
            className="min-w-0 flex-1 rounded-md border border-line bg-paper px-2 py-1 text-[0.8125rem] text-ink outline-none focus:border-accent"
          />
          <select
            value={view}
            data-testid="graph-view"
            onChange={(e) => setView(e.target.value)}
            className="rounded-md border border-line bg-paper px-2 py-1 text-[0.75rem] text-ink outline-none focus:border-accent"
          >
            {VIEWS.map((v) => (
              <option key={v.key} value={v.key}>{v.label}</option>
            ))}
            {selected && <option value="neighbourhood">Neighbourhood (2 hops)</option>}
          </select>
          <select
            value={subjectId}
            data-testid="graph-subject"
            onChange={(e) => setSubjectId(e.target.value ? Number(e.target.value) : '')}
            className="rounded-md border border-line bg-paper px-2 py-1 text-[0.75rem] text-ink outline-none focus:border-accent"
          >
            <option value="">All subjects</option>
            {subjects.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <select
            value={mastery}
            data-testid="graph-mastery"
            onChange={(e) => setMastery(e.target.value)}
            className="rounded-md border border-line bg-paper px-2 py-1 text-[0.75rem] text-ink outline-none focus:border-accent"
          >
            <option value="">Any mastery</option>
            {Object.keys(BADGE_COLOUR).map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
          {/* §13.4 — the job filter dims everything a job did not touch. */}
          <select
            value={jobId}
            data-testid="graph-job"
            onChange={(e) => setJobId(e.target.value ? Number(e.target.value) : '')}
            className="rounded-md border border-line bg-paper px-2 py-1 text-[0.75rem] text-ink outline-none focus:border-accent"
          >
            <option value="">Any run</option>
            {jobs.map((j) => (
              <option key={j.id} value={j.id}>{j.name.split(' · ')[0]}</option>
            ))}
          </select>
        </div>

        <Canvas
          graph={graph}
          onSelect={setSelected}
          onExpand={(id) => { setSelected(id); setView('neighbourhood') }}
        />

        <Legend counts={graph?.counts} />
      </div>

      {/* Right: the work queue */}
      <div className="flex min-h-0 w-full shrink-0 flex-col border-t border-line lg:w-96 lg:border-t-0">
        {selected ? (
          <Inspector conceptId={selected} onClose={() => setSelected(null)} />
        ) : (
          <>
            <div className="flex flex-wrap gap-1 border-b border-line-soft p-2">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setTab(t.key)}
                  data-testid={`tab-${t.key}`}
                  className={[
                    'flex items-center gap-1.5 rounded-md px-2 py-1 text-[0.75rem] transition',
                    tab === t.key
                      ? 'bg-accent-wash font-medium text-accent-deep'
                      : 'text-muted hover:bg-sunken',
                  ].join(' ')}
                >
                  {t.label}
                  <span
                    data-testid={`count-${t.key}`}
                    className="rounded bg-sunken px-1 text-[0.625rem] tabular-nums text-muted"
                  >
                    {counts?.[t.key] ?? 0}
                  </span>
                </button>
              ))}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              <Queue tab={tab} onSelect={setSelected} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------

function Canvas({ graph, onSelect, onExpand }: {
  graph: GraphPayload | undefined
  onSelect: (id: number) => void
  onExpand: (id: number) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const cy = useRef<cytoscape.Core | null>(null)

  const elements = useMemo(() => {
    if (!graph) return []
    return [
      ...graph.nodes.map((n) => ({
        data: {
          id: `n${n.id}`, raw: n.id, label: n.name,
          colour: BADGE_COLOUR[n.badge] ?? BADGE_COLOUR.untested,
          // §13.1 — sized by importance.
          size: 22 + (n.importance ?? 3) * 6,
          opacity: n.dimmed ? 0.22 : 1,
        },
      })),
      ...graph.edges.map((e) => ({
        data: {
          id: `e${e.id}`, source: `n${e.source}`, target: `n${e.target}`,
          colour: RELATION_COLOUR[e.relation_type] ?? RELATION_COLOUR.related_to,
          // §13.1 — dashed when proposed.
          style: e.status === 'proposed' ? 'dashed' : 'solid',
          opacity: e.dimmed ? 0.15 : 0.8,
        },
      })),
    ]
  }, [graph])

  useEffect(() => {
    if (!box.current) return
    if (cy.current) cy.current.destroy()

    cy.current = cytoscape({
      container: box.current,
      elements,
      // Cytoscape's typings do not model `data(...)` mappers for numeric
      // and enum-valued properties, though they are valid at runtime.
      style: ([
        {
          selector: 'node',
          style: {
            'background-color': 'data(colour)',
            width: 'data(size)',
            height: 'data(size)',
            opacity: 'data(opacity)',
            label: 'data(label)',
            'font-size': 9,
            'font-family': 'ui-sans-serif, -apple-system, sans-serif',
            color: '#4A453F',
            'text-valign': 'bottom',
            'text-margin-y': 3,
            'text-max-width': '90px',
            'text-wrap': 'ellipsis',
          },
        },
        {
          selector: 'node:selected',
          style: { 'border-width': 3, 'border-color': '#4F4FC4' },
        },
        {
          selector: 'edge',
          style: {
            width: 1.4,
            'line-color': 'data(colour)',
            'line-style': 'data(style)',
            opacity: 'data(opacity)',
            'curve-style': 'bezier',
            'target-arrow-shape': 'triangle',
            'target-arrow-color': 'data(colour)',
            'arrow-scale': 0.7,
          },
        },
      ] as unknown) as cytoscape.StylesheetStyle[],
      layout: { name: 'cose-bilkent', animate: false, randomize: true,
                idealEdgeLength: 90, nodeRepulsion: 6000 } as never,
      minZoom: 0.2,
      maxZoom: 3,
    })

    cy.current.on('tap', 'node', (event) => onSelect(event.target.data('raw')))
    cy.current.on('dbltap', 'node', (event) => onExpand(event.target.data('raw')))

    return () => { cy.current?.destroy(); cy.current = null }
  }, [elements, onSelect, onExpand])

  return (
    <div className="relative min-h-[24rem] flex-1">
      {/* Cytoscape sets `position: relative` inline on its container, which
          cancels absolute positioning — `inset-0` would leave this at zero
          height and nothing would ever paint. Size it directly instead. */}
      <div ref={box} data-testid="graph-canvas" className="h-full w-full" />
      {graph && graph.nodes.length === 0 && (
        <p data-testid="graph-empty" className="absolute inset-0 grid place-items-center p-6 text-center text-[0.875rem] text-faint">
          Nothing to draw yet. Concepts appear here once you have processed
          some notes.
        </p>
      )}
    </div>
  )
}

function Legend({ counts }: { counts?: { nodes: number; edges: number } }) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-line-soft px-2 py-1.5 text-[0.6875rem] text-muted">
      <span data-testid="graph-counts" className="tabular-nums">
        {counts?.nodes ?? 0} concepts · {counts?.edges ?? 0} edges
      </span>
      <span className="ml-auto flex flex-wrap items-center gap-2">
        {Object.entries(BADGE_COLOUR).map(([badge, colour]) => (
          <span key={badge} className="flex items-center gap-1">
            <span className="size-2 rounded-full" style={{ background: colour }} />
            {badge}
          </span>
        ))}
      </span>
    </div>
  )
}

// --------------------------------------------------------------------------

function Queue({ tab, onSelect }: {
  tab: string
  onSelect: (id: number) => void
}) {
  const qc = useQueryClient()
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['graph'] })
    void qc.invalidateQueries({ queryKey: ['graph-queues'] })
    void qc.invalidateQueries({ queryKey: ['graph-queue', tab] })
  }

  const { data = [] } = useQuery<unknown[]>({
    queryKey: ['graph-queue', tab],
    queryFn: async (): Promise<unknown[]> => {
      if (tab === 'merge_queue') return api.mergeQueue()
      if (tab === 'proposed_edges') return api.proposedEdges()
      if (tab === 'stale_concepts') return api.staleConcepts()
      if (tab === 'auto_merged') return api.autoMerged()
      return api.orphans()
    },
  })

  const act = useMutation({
    mutationFn: async (fn: () => Promise<unknown>) => fn(),
    onSuccess: refresh,
  })

  if (data.length === 0) {
    return (
      <p data-testid={`queue-empty-${tab}`} className="p-4 text-center text-[0.8125rem] text-faint">
        Nothing here.
      </p>
    )
  }

  if (tab === 'merge_queue') {
    return (
      <ul className="space-y-2" data-testid="queue-merge">
        {(data as MergeRow[]).map((r) => {
          return (
            <li key={r.id} className="rounded-lg border border-line bg-surface p-2.5">
              <p className="text-[0.8125rem] text-ink">
                <strong className="font-medium">{r.merged_from_name}</strong>
                <span className="mx-1.5 text-faint">→</span>
                <strong className="font-medium">{r.merged_into_name}</strong>
              </p>
              <p className="mt-0.5 text-[0.6875rem] tabular-nums text-muted">
                similarity {r.similarity?.toFixed(3)}
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <button
                  type="button"
                  data-testid={`merge-accept-${r.id}`}
                  onClick={() => act.mutate(() =>
                    api.doMerge(r.merged_from_id, r.merged_into_id))}
                  className="rounded bg-accent px-2 py-1 text-[0.75rem] font-medium text-white transition hover:bg-accent-deep"
                >
                  Merge
                </button>
                <button
                  type="button"
                  data-testid={`merge-reject-${r.id}`}
                  onClick={() => act.mutate(() => api.rejectMerge(r.id))}
                  className="rounded border border-line px-2 py-1 text-[0.75rem] text-ink transition hover:border-accent"
                >
                  Keep separate
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    )
  }

  if (tab === 'proposed_edges') {
    return (
      <ul className="space-y-2" data-testid="queue-edges">
        {(data as ProposedEdge[]).map((edge) => (
          <li
            key={edge.id}
            data-testid={`edge-${edge.id}`}
            data-cycle={edge.cycle_conflict ? 'true' : 'false'}
            className={[
              'rounded-lg border bg-surface p-2.5',
              edge.cycle_conflict ? 'border-stale' : 'border-line',
            ].join(' ')}
          >
            <p className="text-[0.8125rem] text-ink">
              {edge.source_name}
              <span className="mx-1.5 text-[0.6875rem] uppercase tracking-wide text-muted">
                {edge.relation_type.replace(/_/g, ' ')}
              </span>
              {edge.target_name}
            </p>
            {edge.cycle_conflict && (
              <p data-testid={`cycle-${edge.id}`} className="mt-1 text-[0.6875rem] text-stale">
                Would close a prerequisite loop
                {edge.cycle_path.length > 0 && ` (${edge.cycle_path.length} hops)`}
              </p>
            )}
            <div className="mt-2 flex flex-wrap gap-1.5">
              <button
                type="button"
                data-testid={`edge-accept-${edge.id}`}
                onClick={() => act.mutate(() => api.acceptEdge(edge.id))}
                className="rounded bg-accent px-2 py-1 text-[0.75rem] font-medium text-white transition hover:bg-accent-deep"
              >
                Accept
              </button>
              <button
                type="button"
                data-testid={`edge-flip-${edge.id}`}
                onClick={() => act.mutate(() => api.flipEdge(edge.id))}
                className="rounded border border-line px-2 py-1 text-[0.75rem] text-ink transition hover:border-accent"
              >
                Flip
              </button>
              <button
                type="button"
                data-testid={`edge-reject-${edge.id}`}
                onClick={() => act.mutate(() => api.rejectEdge(edge.id))}
                className="rounded border border-line px-2 py-1 text-[0.75rem] text-ink transition hover:border-accent"
              >
                Reject
              </button>
            </div>
          </li>
        ))}
      </ul>
    )
  }

  if (tab === 'auto_merged') {
    return (
      <ul className="space-y-2" data-testid="queue-auto">
        {(data as MergeRow[]).map((row) => (
          <li key={row.id} className="rounded-lg border border-line bg-surface p-2.5">
            <p className="text-[0.8125rem] text-ink">
              {row.merged_from_name}
              <span className="mx-1.5 text-faint">→</span>
              {row.merged_into_name}
            </p>
            <p className="mt-0.5 text-[0.6875rem] tabular-nums text-muted">
              similarity {row.similarity?.toFixed(3)}
            </p>
            {row.reverted_at ? (
              <p className="mt-1 text-[0.6875rem] text-faint">Undone</p>
            ) : (
              <button
                type="button"
                data-testid={`undo-${row.id}`}
                onClick={() => act.mutate(() => api.revertMerge(row.id))}
                className="mt-2 rounded border border-line px-2 py-1 text-[0.75rem] text-ink transition hover:border-accent"
              >
                Undo
              </button>
            )}
          </li>
        ))}
      </ul>
    )
  }

  // Stale concepts and orphans are both plain concept lists.
  return (
    <ul className="space-y-1" data-testid={`queue-${tab}`}>
      {(data as ConceptRow[]).map((row) => (
          <li key={row.id}>
            <button
              type="button"
              onClick={() => onSelect(row.id)}
              data-testid={`queue-item-${row.id}`}
              className="w-full rounded-md px-2 py-1.5 text-left text-[0.8125rem] text-ink transition hover:bg-sunken"
            >
              {row.name ?? row.canonical_name}
            </button>
          </li>
      ))}
    </ul>
  )
}

// --------------------------------------------------------------------------

/** Spec §13.3 — direct editing. */
function Inspector({ conceptId, onClose }: {
  conceptId: number
  onClose: () => void
}) {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['graph-concept', conceptId],
    queryFn: () => api.graphConcept(conceptId),
  })
  const [name, setName] = useState('')
  const [definition, setDefinition] = useState('')

  useEffect(() => {
    if (!data) return
    setName(data.canonical_name)
    setDefinition(data.definition ?? '')
  }, [data])

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.editConcept(conceptId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['graph-concept', conceptId] })
      void qc.invalidateQueries({ queryKey: ['graph'] })
    },
  })

  if (!data) {
    return <p className="p-4 text-[0.8125rem] text-faint">Loading…</p>
  }

  return (
    <div data-testid="node-inspector" className="min-h-0 flex-1 overflow-y-auto p-3">
      <button
        type="button"
        onClick={onClose}
        data-testid="inspector-close"
        className="mb-2 text-[0.75rem] text-muted transition hover:text-ink"
      >
        ← Work queue
      </button>

      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => name !== data.canonical_name && save.mutate({ canonical_name: name })}
        data-testid="inspector-name"
        className="w-full rounded-md border border-line bg-paper px-2 py-1.5 text-[0.9375rem] font-semibold text-ink outline-none focus:border-accent focus:bg-surface"
      />
      <p className="mt-1 text-[0.6875rem] text-faint">
        Renaming keeps the old name as an alias.
      </p>

      <textarea
        value={definition}
        onChange={(e) => setDefinition(e.target.value)}
        onBlur={() => definition !== (data.definition ?? '') && save.mutate({ definition })}
        rows={4}
        data-testid="inspector-definition"
        className="mt-2 w-full resize-y rounded-md border border-line bg-paper p-2 text-[0.8125rem] leading-relaxed text-ink outline-none focus:border-accent focus:bg-surface"
      />

      <div className="mt-3 grid grid-cols-2 gap-2">
        <Slider label="Importance" value={data.importance ?? 3}
                onCommit={(v) => save.mutate({ importance: v })} />
        <Slider label="Difficulty" value={data.difficulty ?? 3}
                onCommit={(v) => save.mutate({ difficulty: v })} />
      </div>

      <Section title="Coverage">
        <div className="flex flex-wrap gap-1.5">
          {['recall', 'explain', 'apply', 'debug', 'synthesis', 'interview'].map((dim) => (
            <button
              key={dim}
              type="button"
              data-testid={`coverage-${dim}`}
              onClick={() =>
                save.mutate({
                  coverage_profile: {
                    ...data.coverage_profile,
                    [dim]: !data.coverage_profile?.[dim],
                  },
                })
              }
              className={[
                'rounded px-1.5 py-0.5 text-[0.6875rem] transition',
                data.coverage_profile?.[dim]
                  ? 'bg-accent-wash text-accent-deep'
                  : 'bg-sunken text-faint',
              ].join(' ')}
            >
              {dim}
            </button>
          ))}
        </div>
      </Section>

      {data.aliases.length > 0 && (
        <Section title="Also known as">
          <p data-testid="inspector-aliases" className="text-[0.75rem] text-muted">
            {data.aliases.map((a) => a.alias).join(', ')}
          </p>
        </Section>
      )}

      <Section title="Mastery">
        <p className="text-[0.75rem] text-muted">
          <span data-testid="inspector-badge">{data.mastery.badge}</span>
          {data.mastery.mastery !== null && ` · ${(data.mastery.mastery * 100).toFixed(0)}%`}
        </p>
      </Section>

      {data.edges.length > 0 && (
        <Section title="Connections">
          <ul className="space-y-0.5" data-testid="inspector-edges">
            {data.edges.map((edge) => (
              <li key={edge.id} className="text-[0.75rem] text-muted">
                {edge.direction === 'out' ? '→ ' : '← '}
                {edge.other_name}
                <span className="ml-1 text-faint">
                  ({edge.relation_type.replace(/_/g, ' ')})
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {data.sources.length > 0 && (
        <Section title="From your notes">
          <ul className="space-y-1" data-testid="inspector-sources">
            {data.sources.map((source, i) => (
              <li
                key={i}
                className={`text-[0.75rem] leading-relaxed ${source.invalidated ? 'text-faint line-through' : 'text-muted'}`}
              >
                {source.text}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Cost">
        <p data-testid="inspector-cost" className="text-[0.75rem] tabular-nums text-muted">
          {(data.cost.input_tokens + data.cost.output_tokens).toLocaleString()} tokens
          {' · '}${data.cost.estimated_cost_usd.toFixed(4)}
          {' · '}{data.cost.generations} generation
          {data.cost.generations === 1 ? '' : 's'}
        </p>
      </Section>
    </div>
  )
}

function Slider({ label, value, onCommit }: {
  label: string
  value: number
  onCommit: (v: number) => void
}) {
  const [local, setLocal] = useState(value)
  useEffect(() => setLocal(value), [value])
  return (
    <label className="block">
      <span className="mb-1 block text-[0.6875rem] text-ink-soft">
        {label} — {local}
      </span>
      <input
        type="range"
        min={1}
        max={5}
        step={1}
        value={local}
        data-testid={`inspector-${label.toLowerCase()}`}
        onChange={(e) => setLocal(Number(e.target.value))}
        onPointerUp={() => onCommit(local)}
        onKeyUp={() => onCommit(local)}
        className="w-full accent-[var(--color-accent)]"
      />
    </label>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-3 border-t border-line-soft pt-2.5">
      <h3 className="mb-1.5 text-[0.6875rem] font-semibold uppercase tracking-wide text-muted">
        {title}
      </h3>
      {children}
    </section>
  )
}
