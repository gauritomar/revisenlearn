import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type PendingBlock, type PipelineJob } from '../lib/api'
import { useUI } from '../store/ui'

/** Spec §14 — the **Process notes** button, showing the unprocessed count.
 *
 *  Principle §1.3 **[LOCKED]**: "Nothing is automatic. The user presses a
 *  button to process notes. The system never silently spends money." So this
 *  is the only thing in the app that starts a job, and it says plainly that it
 *  will call a model before it does.
 */
const ACTIVE = new Set(['queued', 'running'])

export function ProcessNotes({ pendingHint }: { pendingHint?: number }) {
  const qc = useQueryClient()
  const [confirming, setConfirming] = useState(false)

  const { data: pending } = useQuery({
    queryKey: ['pipeline-pending'],
    queryFn: () => api.pending(),
  })
  const { data: jobs = [] } = useQuery({
    queryKey: ['pipeline-jobs'],
    queryFn: api.jobs,
    // While a job is in flight, poll so the stage label actually moves.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((j: PipelineJob) => ACTIVE.has(j.status))
        ? 1000
        : false,
  })

  const active = jobs.find((j) => ACTIVE.has(j.status))
  const latest = jobs[0]
  const count = pending?.unprocessed_blocks ?? pendingHint ?? 0

  const run = useMutation({
    mutationFn: () => api.runPipeline(null),
    onSuccess: async () => {
      setConfirming(false)
      await qc.invalidateQueries({ queryKey: ['pipeline-jobs'] })
    },
  })

  // When a job finishes, everything it touched is stale.
  useEffect(() => {
    if (active || !latest || latest.status !== 'succeeded') return
    void qc.invalidateQueries({ queryKey: ['pipeline-pending'] })
    void qc.invalidateQueries({ queryKey: ['concepts'] })
    void qc.invalidateQueries({ queryKey: ['note'] })
  }, [active, latest?.id, latest?.status, qc])

  if (active) {
    return (
      <span
        data-testid="pipeline-running"
        data-stage={active.stage ?? 'queued'}
        className="flex items-center gap-2 rounded-md border border-line bg-paper px-2.5 py-1 text-[0.75rem] text-muted"
      >
        <span className="size-1.5 animate-pulse rounded-full bg-accent" aria-hidden="true" />
        {active.name.split(' · ')[0]} · {active.stage ?? 'queued'}
      </span>
    )
  }

  if (confirming) {
    return <Preview count={count} onCancel={() => setConfirming(false)}
                    onConfirm={() => run.mutate()} pending={run.isPending} />
  }

  return (
    <span className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => setConfirming(true)}
        disabled={count === 0}
        data-testid="process-notes"
        data-pending={count}
        title={count === 0 ? 'Nothing new to process' : undefined}
        className={[
          'flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[0.75rem] transition',
          count === 0
            ? 'cursor-not-allowed border-line bg-paper text-faint'
            : 'border-accent bg-paper text-accent-deep hover:bg-accent-wash',
        ].join(' ')}
      >
        Process notes
        {count > 0 && (
          <span className="rounded bg-accent-wash px-1.5 py-0.5 text-[0.6875rem] tabular-nums text-accent-deep">
            {count}
          </span>
        )}
      </button>
      {run.isError && (
        <span data-testid="process-notes-error" className="text-[0.75rem] text-stale">
          {(run.error as Error).message.slice(0, 120)}
        </span>
      )}
    </span>
  )
}


/** Consolidated addendum §7 — the block preview.
 *
 *  "This is the moment the user is about to spend real money; they should see
 *  what's paying for it." So the confirmation is not a yes/no box: it lists
 *  every block that would be sent, with a snippet, grouped by note.
 */
function Preview({ count, onConfirm, onCancel, pending }: {
  count: number
  onConfirm: () => void
  onCancel: () => void
  pending: boolean
}) {
  const { data } = useQuery({
    queryKey: ['pipeline-preview'],
    queryFn: () => api.pendingPreview(),
    // This list is the basis for spending money, so it is never served from
    // a cache: it is fetched fresh every time the confirmation opens.
    staleTime: 0,
    refetchOnMount: 'always',
  })

  const openPage = useUI((s) => s.openPage)

  const grouped = new Map<string, PendingBlock[]>()
  for (const block of data?.blocks ?? []) {
    const list = grouped.get(block.note_title) ?? []
    list.push(block)
    grouped.set(block.note_title, list)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-ink/15 px-4 pt-[10vh] backdrop-blur-[2px]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel() }}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="What will be sent"
        data-testid="process-preview"
        className="flex max-h-[70vh] w-full max-w-xl flex-col rounded-xl border border-line bg-surface shadow-xl"
      >
        <div className="border-b border-line-soft p-4">
          <h2 className="text-[0.9375rem] font-semibold tracking-tight text-ink">
            Send {count} block{count === 1 ? '' : 's'} to Gemini?
          </h2>
          <p className="mt-1 text-[0.75rem] leading-relaxed text-muted">
            This is what will be sent, and it costs money.
            {data ? ` Roughly ${data.estimated_tokens.toLocaleString()} input tokens.` : ''}
          </p>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-3" data-testid="preview-blocks">
          {!data ? (
            <p className="text-[0.8125rem] text-faint">Loading…</p>
          ) : (
            [...grouped.entries()].map(([title, blocks]) => (
              <section key={title} className="mb-3">
                {/* The heading is the way back to the writing: seeing a
                    snippet you do not recognise should not mean closing this
                    and hunting for it. */}
                <h3 className="mb-1 text-[0.75rem] font-medium text-ink">
                  {blocks[0]?.page_kind && blocks[0]?.page_id ? (
                    <button
                      type="button"
                      onClick={() => {
                        openPage(blocks[0].page_kind!, blocks[0].page_id!)
                        onCancel()
                      }}
                      data-testid={`preview-open-${blocks[0].page_kind}-${blocks[0].page_id}`}
                      className="rounded px-1 py-0.5 text-accent-deep transition hover:bg-accent-wash"
                    >
                      {title} →
                    </button>
                  ) : (
                    title
                  )}
                </h3>
                <ul className="space-y-0.5">
                  {blocks.map((block) => (
                    <li
                      key={block.note_block_id}
                      data-testid={`preview-block-${block.note_block_id}`}
                      className="flex items-baseline gap-2 rounded px-1.5 py-1 text-[0.75rem] odd:bg-paper"
                    >
                      <span
                        className={`shrink-0 text-[0.625rem] uppercase tracking-wide ${
                          block.state === 'stale' ? 'text-stale' : 'text-faint'
                        }`}
                      >
                        {block.state === 'stale' ? 'edited' : 'new'}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-ink-soft">
                        {block.snippet}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ))
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-line-soft p-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-[0.8125rem] text-muted transition hover:bg-sunken hover:text-ink"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            data-testid="process-notes-confirm"
            className="rounded-md bg-accent px-3.5 py-1.5 text-[0.8125rem] font-medium text-white transition hover:bg-accent-deep disabled:opacity-50"
          >
            {pending ? 'Starting…' : 'Yes, process'}
          </button>
        </div>
      </div>
    </div>
  )
}
