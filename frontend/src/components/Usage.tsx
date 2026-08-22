import { useQuery } from '@tanstack/react-query'

import { api, type UsageSummary } from '../lib/api'

/** The Usage screen (spec §12.6 **[LOCKED]**).
 *
 *  "Gemini's API does not expose account spend", so every figure here is
 *  derived from token counts. The disclaimer is required, not decorative.
 *
 *  The cap is **soft only**: a banner at 80%, a stronger one at 100% plus a
 *  confirmation before each further call. "Never hard-block — being unable to
 *  study because of a budget setting is worse than the overspend."
 */
export function Usage() {
  const { data } = useQuery({ queryKey: ['usage'], queryFn: api.usageSummary })
  const { data: byConcept = [] } = useQuery({
    queryKey: ['usage-by-concept'],
    queryFn: () => api.usageByConcept(50),
  })
  const { data: hierarchy } = useQuery({
    queryKey: ['usage-hierarchy'],
    queryFn: api.usageByHierarchy,
  })

  if (!data) {
    return <div className="p-6 text-[0.8125rem] text-faint">Loading…</div>
  }

  return (
    <div data-testid="usage" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <h2 className="text-xl font-semibold tracking-tight text-ink">Usage</h2>
      <p data-testid="usage-disclaimer" className="mt-1 text-[0.8125rem] leading-relaxed text-muted">
        {data.disclaimer}.{' '}
        <a
          href={data.billing_console_url}
          target="_blank"
          rel="noreferrer"
          className="text-accent-deep underline"
        >
          Google Cloud console
        </a>
      </p>

      <CapBanner cap={data.cap} />

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label={`Spent (${data.month})`} value={`$${data.spent_usd.toFixed(4)}`}
              testid="usage-spent" />
        <Stat
          label="In ₹"
          value={data.spent_gbp === null ? '—' : `₹${data.spent_gbp.toFixed(2)}`}
          hint={data.fx_rate === null ? 'Set an FX rate in Settings' : undefined}
        />
        <Stat label="Calls" value={data.calls} />
        <Stat
          label="Tokens"
          value={(data.input_tokens + data.output_tokens).toLocaleString()}
        />
      </div>

      {data.unpriced_calls > 0 && (
        <p className="mt-2 text-[0.75rem] text-faint">
          {data.unpriced_calls} call(s) used a model with no price on file, so
          the total is a lower bound.
        </p>
      )}

      <Section title="This month, day by day">
        <Sparkline points={data.daily.map((d) => d.usd)} />
      </Section>

      <Section title="By task">
        {data.by_task.length === 0 ? (
          <Empty />
        ) : (
          <Table
            head={['Task', 'Calls', 'Tokens', 'Cost']}
            rows={data.by_task.map((t) => [
              t.task.replace(/_/g, ' '),
              String(t.calls),
              (t.input_tokens + t.output_tokens).toLocaleString(),
              `$${t.usd.toFixed(4)}`,
            ])}
            testid="usage-by-task"
          />
        )}
      </Section>

      <Section title="By subject and topic">
        {!hierarchy || hierarchy.by_subject.length === 0 ? (
          <Empty />
        ) : (
          <Table
            head={['Subject', 'Topic', 'Cost']}
            rows={[
              ...hierarchy.by_subject.map((s) => [s.subject, '—',
                                                  `$${s.usd.toFixed(4)}`]),
              ...hierarchy.by_topic.map((t) => [t.subject, t.topic,
                                                `$${t.usd.toFixed(4)}`]),
            ]}
            testid="usage-by-hierarchy"
          />
        )}
      </Section>

      <Section title="By concept">
        {byConcept.length === 0 ? (
          <Empty />
        ) : (
          <Table
            head={['Concept', 'Tokens', 'Cost', 'Generations']}
            rows={byConcept.map((c) => [
              c.concept_name,
              `${(c.tokens / 1000).toFixed(1)}k`,
              c.gbp === null ? `$${c.usd.toFixed(4)}` : `₹${c.gbp.toFixed(2)}`,
              String(c.generations),
            ])}
            testid="usage-by-concept"
          />
        )}
      </Section>
    </div>
  )
}

function CapBanner({ cap }: { cap: UsageSummary['cap'] }) {
  if (cap.level === 'none' || cap.level === 'ok') {
    return cap.cap_usd === null ? (
      <p className="mt-3 text-[0.75rem] text-faint">
        No monthly cap set. You can add one in Settings.
      </p>
    ) : (
      <div className="mt-3" data-testid="cap-bar" data-level={cap.level}>
        <div className="h-1.5 overflow-hidden rounded-full bg-sunken">
          <div
            className="h-full rounded-full bg-accent"
            style={{ width: `${Math.min(100, (cap.ratio ?? 0) * 100)}%` }}
          />
        </div>
        <p className="mt-1 text-[0.75rem] tabular-nums text-muted">
          ${cap.spent_usd.toFixed(2)} of ${cap.cap_usd.toFixed(2)}
        </p>
      </div>
    )
  }

  const over = cap.level === 'over'
  return (
    <div
      data-testid="cap-banner"
      data-level={cap.level}
      className={[
        'mt-3 rounded-lg border p-3',
        over ? 'border-stale bg-stale-wash' : 'border-line bg-paper',
      ].join(' ')}
    >
      <p className={`text-[0.875rem] font-medium ${over ? 'text-ink' : 'text-ink-soft'}`}>
        {over
          ? `You are over your monthly cap — $${cap.spent_usd.toFixed(2)} of $${cap.cap_usd?.toFixed(2)}.`
          : `You are at ${Math.round((cap.ratio ?? 0) * 100)}% of your monthly cap.`}
      </p>
      <p className="mt-1 text-[0.75rem] leading-relaxed text-muted">
        {over
          ? 'Nothing is blocked. Processing notes will ask you to confirm once before each run.'
          : 'Nothing changes yet; this is just so the number is not a surprise.'}
      </p>
    </div>
  )
}

/** A plain inline sparkline. No library for eleven rectangles. */
function Sparkline({ points }: { points: number[] }) {
  const max = Math.max(...points, 0.000001)
  return (
    <div data-testid="usage-sparkline" className="flex h-12 items-end gap-0.5">
      {points.map((value, i) => (
        <span
          key={i}
          title={`$${value.toFixed(4)}`}
          className="min-w-0 flex-1 rounded-sm bg-accent"
          style={{
            height: `${Math.max(2, (value / max) * 100)}%`,
            opacity: value === 0 ? 0.18 : 1,
          }}
        />
      ))}
    </div>
  )
}

function Table({ head, rows, testid }: {
  head: string[]
  rows: string[][]
  testid: string
}) {
  return (
    <div className="overflow-x-auto">
      <table data-testid={testid} className="w-full text-[0.75rem]">
        <thead>
          <tr className="text-left text-faint">
            {head.map((h) => <th key={h} className="pb-1 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody className="tabular-nums text-ink-soft">
          {rows.map((row, i) => (
            <tr key={i} className="odd:bg-paper">
              {row.map((cell, j) => (
                <td key={j} className="max-w-[14rem] truncate py-1 pr-2">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-4 rounded-lg border border-line bg-surface p-4">
      <h3 className="mb-2.5 text-[0.8125rem] font-semibold tracking-tight text-ink">
        {title}
      </h3>
      {children}
    </section>
  )
}

const Empty = () => (
  <p className="text-[0.8125rem] text-faint">Nothing spent yet.</p>
)

function Stat({ label, value, hint, testid }: {
  label: string
  value: React.ReactNode
  hint?: string
  testid?: string
}) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3" data-testid={testid}>
      <div className="text-[1.0625rem] font-semibold tabular-nums text-ink">
        {value}
      </div>
      <div className="mt-0.5 text-[0.6875rem] text-muted">{label}</div>
      {hint && <div className="text-[0.625rem] text-faint">{hint}</div>}
    </div>
  )
}

// --------------------------------------------------------------------------

/** Spec §14.4 — "A `?` overlay lists them." Minimal only, nothing modal,
 *  nothing vim-like. */
const SHORTCUTS: Array<[string, string]> = [
  ['⌘K', 'Global search'],
  ['⌘S', 'Force save'],
  ['⌘↵', 'Submit answer'],
  ['1–4', 'Select an MCQ option'],
  ['Space', 'Next question'],
  ['Esc', 'Close a dialog'],
  ['?', 'This list'],
]

export function ShortcutOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/15 px-4 backdrop-blur-[2px]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard shortcuts"
        data-testid="shortcut-overlay"
        className="w-full max-w-sm rounded-xl border border-line bg-surface p-4 shadow-xl"
      >
        <h2 className="text-[0.9375rem] font-semibold tracking-tight text-ink">
          Keyboard shortcuts
        </h2>
        <ul className="mt-3 space-y-1.5">
          {SHORTCUTS.map(([key, what]) => (
            <li key={key} className="flex items-baseline gap-3">
              <kbd className="min-w-[3.5rem] rounded border border-line bg-paper px-1.5 py-0.5 text-center text-[0.6875rem] text-ink-soft">
                {key}
              </kbd>
              <span className="text-[0.8125rem] text-ink">{what}</span>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={onClose}
          data-testid="shortcut-close"
          className="mt-4 w-full rounded-md border border-line px-3 py-1.5 text-[0.8125rem] text-ink transition hover:border-accent"
        >
          Close
        </button>
      </div>
    </div>
  )
}
