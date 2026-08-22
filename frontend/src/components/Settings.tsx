import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type AppMeta } from '../lib/api'

/** Spec §14 Settings. §17 puts the backup controls and the Markdown export
 *  here.
 *
 *  Consolidated addendum §8: similarity thresholds, FSRS parameters, priority
 *  weights and session sizes were live in the backend all along and are now
 *  editable here. Model assignments stay read-only on purpose — spec §12.2
 *  keeps swapping a model a config change.
 */
export function Settings({ meta }: { meta: AppMeta | undefined }) {
  const qc = useQueryClient()

  const { data: backups } = useQuery({
    queryKey: ['backups'],
    queryFn: api.backupList,
  })

  const backupNow = useMutation({
    mutationFn: api.backupNow,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['backups'] }),
  })

  const [exported, setExported] = useState<string | null>(null)
  const exportNotes = useMutation({
    mutationFn: () => api.exportMarkdown(),
    onSuccess: (result) =>
      setExported(
        `${result.file_count} note${result.file_count === 1 ? '' : 's'} → ${result.path}`,
      ),
  })

  return (
    <div data-testid="settings" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <h2 className="mb-5 text-xl font-semibold tracking-tight text-ink">Settings</h2>

      {/* --- API key (spec §17) --- */}
      <Section title="API key">
        <div className="flex flex-wrap items-center gap-2">
          <span
            data-testid="api-key-status"
            data-present={meta?.api_key.present ? 'true' : 'false'}
            className="text-[0.8125rem] text-ink"
          >
            {meta?.api_key.present ? (
              <>
                Present, from <strong className="font-medium">{meta.api_key.source}</strong>
              </>
            ) : (
              'Not configured'
            )}
          </span>
        </div>
        <p className="mt-2 text-[0.75rem] leading-relaxed text-muted">
          The key is read from the macOS Keychain, then <code>GEMINI_API_KEY</code>,
          then <code>creds/</code>. It is never stored in the database, never
          returned by this screen, and never logged.
          {meta?.api_key.source === 'creds-file' && (
            <>
              {' '}
              <span className="text-stale">
                It is currently in a file, which the spec does not allow. Move it
                with{' '}
                <code>uv run python -m revisenlearn.credentials --import-to-keychain</code>.
              </span>
            </>
          )}
        </p>
        <p className="mt-2 text-[0.75rem] leading-relaxed text-faint">
          Every model call is logged with its prompt version, model and token
          counts. Usage shows what they cost.
        </p>
      </Section>

      {/* --- Backup (spec §17) --- */}
      <Section title="Backup">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => backupNow.mutate()}
            disabled={backupNow.isPending}
            data-testid="backup-now"
            className="rounded-md bg-accent px-3 py-1.5 text-[0.8125rem] font-medium text-white transition hover:bg-accent-deep disabled:opacity-50"
          >
            {backupNow.isPending ? 'Backing up…' : 'Back up now'}
          </button>
          <span className="text-[0.75rem] text-muted">
            {backups ? `${backups.backups.length} kept · ${formatBytes(backups.total_bytes)}` : '—'}
          </span>
        </div>

        <p className="mt-2 text-[0.75rem] leading-relaxed text-muted">
          A compacted copy is written automatically at the first launch after
          03:00 each day. Seven daily and four weekly copies are kept; the rest
          are removed.
        </p>

        {backupNow.isError && (
          <p data-testid="backup-error" className="mt-2 text-[0.8125rem] text-stale">
            {(backupNow.error as Error).message}
          </p>
        )}

        {backups && backups.backups.length > 0 && (
          <>
            <p className="mt-3 truncate font-mono text-[0.6875rem] text-faint">
              {backups.directory}
            </p>
            <ul data-testid="backup-list" className="mt-1.5 space-y-0.5">
              {backups.backups.slice(0, 12).map((b) => (
                <li
                  key={b.name}
                  className="flex items-baseline justify-between gap-2 rounded px-1.5 py-1 text-[0.75rem] odd:bg-paper"
                >
                  <span className="truncate font-mono text-ink-soft">{b.name}</span>
                  <span className="shrink-0 tabular-nums text-faint">
                    {formatBytes(b.size_bytes)}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>

      {/* --- Export (spec §17) --- */}
      <Section title="Export">
        <button
          type="button"
          onClick={() => exportNotes.mutate()}
          disabled={exportNotes.isPending}
          data-testid="export-markdown"
          className="rounded-md border border-line bg-paper px-3 py-1.5 text-[0.8125rem] text-ink transition hover:border-accent hover:text-accent-deep disabled:opacity-50"
        >
          {exportNotes.isPending ? 'Exporting…' : 'Export all notes as Markdown'}
        </button>

        <p className="mt-2 text-[0.75rem] leading-relaxed text-muted">
          One folder per Subject / Topic / Subtopic, one file per note, with
          front-matter giving the date and resource. Plain files — nothing there
          needs this app to read it.
        </p>

        {exported && (
          <p
            data-testid="export-result"
            className="mt-2 break-all font-mono text-[0.6875rem] text-mastery-3"
          >
            {exported}
          </p>
        )}
        {exportNotes.isError && (
          <p data-testid="export-error" className="mt-2 text-[0.8125rem] text-stale">
            {(exportNotes.error as Error).message}
          </p>
        )}
      </Section>

      <InterviewSection />
      <BudgetSection />

      <TuningSection />
      <ModelSection />
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-3 rounded-lg border border-line bg-surface p-4">
      <h3 className="mb-2.5 text-[0.8125rem] font-semibold tracking-tight text-ink">
        {title}
      </h3>
      {children}
    </section>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1_048_576).toFixed(1)} MB`
}


/** Spec §10.1 — "A single Settings toggle, Interview mode, unsuspends them
 *  all. Default off. Turn it on around month 4." */
function InterviewSection() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['interview-mode'],
    queryFn: api.interviewMode,
  })
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api.setInterviewMode(enabled),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['interview-mode'] })
      void qc.invalidateQueries({ queryKey: ['revision-dashboard'] })
    },
  })

  return (
    <Section title="Interview mode">
      <label className="flex items-center gap-2 text-[0.8125rem] text-ink">
        <input
          type="checkbox"
          checked={data?.enabled ?? false}
          data-testid="interview-mode"
          onChange={(e) => toggle.mutate(e.target.checked)}
          className="size-4 accent-[var(--color-accent)]"
        />
        Include interview questions in revision
      </label>
      <p className="mt-2 text-[0.75rem] leading-relaxed text-muted">
        Interview review items are created for every concept but stay suspended
        until this is on. Turning it on unsuspends them all; turning it off
        puts them back to sleep without losing their history.
      </p>
      {toggle.data && (
        <p data-testid="interview-changed" className="mt-1 text-[0.75rem] text-faint">
          {toggle.data.items_changed} item(s) changed.
        </p>
      )}
    </Section>
  )
}

/** Spec §12.6 — FX rate and the soft monthly cap. */
function BudgetSection() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const [fx, setFx] = useState('')
  const [cap, setCap] = useState('')

  useEffect(() => {
    if (!data) return
    setFx(data.values.fx_rate_usd_to_gbp ? String(data.values.fx_rate_usd_to_gbp) : '')
    setCap(data.values.monthly_cap_usd ? String(data.values.monthly_cap_usd) : '')
  }, [data])

  const save = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.patchSettings(values),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['settings'] })
      void qc.invalidateQueries({ queryKey: ['usage'] })
    },
  })

  const runAdaptive = useMutation({ mutationFn: api.adaptiveCoverage })

  return (
    <Section title="Budget">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-[0.6875rem] font-medium text-ink-soft">
            FX rate (1 USD in ₹)
          </span>
          <input
            value={fx}
            data-testid="fx-rate"
            onChange={(e) => setFx(e.target.value)}
            onBlur={() => save.mutate({
              fx_rate_usd_to_gbp: fx ? Number(fx) : null,
            })}
            placeholder="83.5"
            className="w-full rounded-md border border-line bg-paper px-2 py-1.5 text-[0.8125rem] text-ink outline-none focus:border-accent focus:bg-surface"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[0.6875rem] font-medium text-ink-soft">
            Monthly cap (USD)
          </span>
          <input
            value={cap}
            data-testid="monthly-cap"
            onChange={(e) => setCap(e.target.value)}
            onBlur={() => save.mutate({
              monthly_cap_usd: cap ? Number(cap) : null,
            })}
            placeholder="20"
            className="w-full rounded-md border border-line bg-paper px-2 py-1.5 text-[0.8125rem] text-ink outline-none focus:border-accent focus:bg-surface"
          />
        </label>
      </div>
      <p className="mt-2 text-[0.75rem] leading-relaxed text-muted">
        The cap is a soft one. At 80% you get a note, at 100% a confirmation
        before each run. Nothing is ever blocked — not being able to study
        because of a budget setting would be worse than the overspend.
      </p>

      <div className="mt-3 border-t border-line-soft pt-3">
        <button
          type="button"
          onClick={() => runAdaptive.mutate()}
          disabled={runAdaptive.isPending}
          data-testid="run-adaptive"
          className="rounded-md border border-line bg-paper px-3 py-1.5 text-[0.8125rem] text-ink transition hover:border-accent disabled:opacity-50"
        >
          {runAdaptive.isPending ? 'Running…' : 'Widen coverage where earned'}
        </button>
        <p className="mt-2 text-[0.75rem] leading-relaxed text-muted">
          Adds <code>debug</code> to concepts whose <code>apply</code> has
          lapsed twice, and <code>synthesis</code> to well-connected concepts
          you already explain and apply well. Never removes a dimension.
        </p>
        {runAdaptive.data && (
          <p data-testid="adaptive-result" className="mt-1 text-[0.75rem] text-mastery-3">
            Added debug to {runAdaptive.data.added_debug.length}, synthesis to{' '}
            {runAdaptive.data.added_synthesis.length}.
          </p>
        )}
      </div>
    </Section>
  )
}


/** Consolidated addendum §8.
 *
 *  Similarity thresholds, FSRS parameters, priority weights and session
 *  defaults were all live in the backend and reachable via
 *  `PATCH /api/settings` — only the Settings UI said "Still to come", which
 *  was simply wrong. These are the missing controls.
 */
function TuningSection() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const save = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.patchSettings(values),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['settings'] })
      void qc.invalidateQueries({ queryKey: ['practice-defaults'] })
      void qc.invalidateQueries({ queryKey: ['revision-dashboard'] })
    },
  })

  const values = (data?.values ?? {}) as Record<string, never>
  const thresholds = (values.similarity_thresholds ?? {}) as Record<string, number>
  const fsrs = (values.fsrs ?? {}) as Record<string, number | boolean>
  const weights = (values.priority_weights ?? {}) as Record<string, number>
  const sessions = (values.session_defaults ?? {}) as Record<string, number>

  return (
    <>
      <Section title="Concept identity">
        <p className="mb-2.5 text-[0.75rem] leading-relaxed text-muted">
          Above the merge threshold two concepts are merged automatically;
          between the two they go to the graph console's merge queue for you to
          decide.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <NumberField
            label="Auto-merge at" testid="threshold-auto"
            value={thresholds.auto_merge ?? 0.92} step="0.01" min="0" max="1"
            onCommit={(v) => save.mutate({
              similarity_thresholds: {
                ...thresholds, auto_merge: v,
                merge_queue: thresholds.merge_queue ?? 0.82,
              },
            })}
          />
          <NumberField
            label="Queue for review at" testid="threshold-queue"
            value={thresholds.merge_queue ?? 0.82} step="0.01" min="0" max="1"
            onCommit={(v) => save.mutate({
              similarity_thresholds: {
                ...thresholds, merge_queue: v,
                auto_merge: thresholds.auto_merge ?? 0.92,
              },
            })}
          />
        </div>
      </Section>

      <Section title="Scheduling">
        <div className="grid gap-3 sm:grid-cols-2">
          <NumberField
            label="Desired retention" testid="fsrs-retention"
            value={Number(fsrs.desired_retention ?? 0.9)}
            step="0.01" min="0.7" max="0.99"
            onCommit={(v) => save.mutate({ fsrs: { ...fsrs, desired_retention: v } })}
          />
          <NumberField
            label="Maximum interval (days)" testid="fsrs-max-interval"
            value={Number(fsrs.maximum_interval ?? 365)} step="1" min="1" max="3650"
            onCommit={(v) => save.mutate({ fsrs: { ...fsrs, maximum_interval: v } })}
          />
        </div>
        <p className="mt-3 mb-1.5 text-[0.6875rem] font-medium text-ink-soft">
          Queue priority weights
        </p>
        <div className="grid gap-3 sm:grid-cols-4">
          {(['w_overdue', 'w_lapse', 'w_gap', 'w_interview'] as const).map((key) => (
            <NumberField
              key={key}
              label={key.replace('w_', '')}
              testid={`weight-${key}`}
              value={weights[key] ?? { w_overdue: 0.5, w_lapse: 0.3, w_gap: 0.4, w_interview: 0.3 }[key]}
              step="0.05" min="0" max="5"
              onCommit={(v) => save.mutate({ priority_weights: { ...weights, [key]: v } })}
            />
          ))}
        </div>
        <p className="mt-2 text-[0.75rem] leading-relaxed text-muted">
          These are the spec's own starting guesses. Every review is logged with
          its before and after state, so they can be fitted from evidence later.
        </p>
      </Section>

      <Section title="Session sizes">
        <div className="grid gap-3 sm:grid-cols-2">
          <NumberField
            label="Practice questions" testid="session-practice"
            value={sessions.practice_count ?? 20} step="1" min="1" max="200"
            onCommit={(v) => save.mutate({
              session_defaults: { ...sessions, practice_count: v },
            })}
          />
          <NumberField
            label="Revision questions" testid="session-revision"
            value={sessions.revision_count ?? 5} step="1" min="1" max="100"
            onCommit={(v) => save.mutate({
              session_defaults: { ...sessions, revision_count: v },
            })}
          />
        </div>
        <p className="mt-2 text-[0.75rem] leading-relaxed text-muted">
          What Practice and Revision preselect. Five is a deliberately small
          revision default — starting is the hard part.
        </p>
      </Section>
    </>
  )
}

/** §8 — model assignments are genuinely config-file-only, matching spec §12.2
 *  ("swapping a model is a config change, never a code change"). Shown
 *  read-only, with where to change them, rather than mislabelled. */
function ModelSection() {
  const { data } = useQuery({ queryKey: ['providers'], queryFn: api.providers })

  return (
    <Section title="Models">
      {!data ? (
        <p className="text-[0.8125rem] text-faint">Loading…</p>
      ) : (
        <table data-testid="model-assignments" className="w-full text-[0.75rem]">
          <thead>
            <tr className="text-left text-faint">
              <th className="pb-1 font-medium">Task</th>
              <th className="pb-1 font-medium">Model</th>
              <th className="pb-1 font-medium">Thinking</th>
              <th className="pb-1 font-medium">Mode</th>
            </tr>
          </thead>
          <tbody className="text-ink-soft">
            {Object.entries(data.tasks).map(([task, cfg]) => (
              <tr key={task} className="odd:bg-paper">
                <td className="py-1 pr-2">{task.replace(/_/g, ' ')}</td>
                <td className="py-1 pr-2 font-mono">{cfg.model}</td>
                <td className="py-1 pr-2">{cfg.thinking_level ?? '—'}</td>
                <td className="py-1">{cfg.mode}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-2 text-[0.75rem] leading-relaxed text-muted">
        Read-only here by design. Swapping a model is a config change — edit{' '}
        <code>config/providers.yaml</code> and restart. Prompt versions are
        files under <code>src/revisenlearn/prompts/</code>; a prompt is never
        edited in place, only superseded by a new version.
      </p>
    </Section>
  )
}

function NumberField({ label, testid, value, step, min, max, onCommit }: {
  label: string
  testid: string
  value: number
  step: string
  min: string
  max: string
  onCommit: (v: number) => void
}) {
  const [local, setLocal] = useState(String(value))
  useEffect(() => setLocal(String(value)), [value])
  return (
    <label className="block">
      <span className="mb-1 block text-[0.6875rem] font-medium text-ink-soft">
        {label}
      </span>
      <input
        type="number"
        value={local}
        step={step}
        min={min}
        max={max}
        data-testid={testid}
        onChange={(e) => setLocal(e.target.value)}
        onBlur={() => {
          const parsed = Number(local)
          if (!Number.isNaN(parsed) && parsed !== value) onCommit(parsed)
        }}
        className="w-full rounded-md border border-line bg-paper px-2 py-1.5 text-[0.8125rem] tabular-nums text-ink outline-none focus:border-accent focus:bg-surface"
      />
    </label>
  )
}
