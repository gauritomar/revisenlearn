import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type PipelineJob } from '../lib/api'

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
    return (
      <span className="flex flex-wrap items-center gap-2 rounded-md border border-accent bg-accent-wash px-2.5 py-1 text-[0.75rem]">
        <span className="text-accent-deep">
          Send {count} block{count === 1 ? '' : 's'} to Gemini?
        </span>
        <button
          type="button"
          onClick={() => run.mutate()}
          disabled={run.isPending}
          data-testid="process-notes-confirm"
          className="rounded bg-accent px-2 py-0.5 font-medium text-white transition hover:bg-accent-deep disabled:opacity-50"
        >
          {run.isPending ? 'Starting…' : 'Yes, process'}
        </button>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className="text-muted transition hover:text-ink"
        >
          Cancel
        </button>
      </span>
    )
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
