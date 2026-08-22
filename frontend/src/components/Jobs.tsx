import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type PipelineJob } from '../lib/api'

/** Spec §8.5 — "Every job has a detail page: what it created, updated, merged,
 *  and proposed; which items need attention; its token cost. This is how the
 *  user does periodic curation without living in the graph."
 */
const ACTIVE = new Set(['queued', 'running'])

export function Jobs() {
  const [openId, setOpenId] = useState<number | null>(null)
  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ['pipeline-jobs'],
    queryFn: api.jobs,
    refetchInterval: (query) =>
      (query.state.data ?? []).some((j: PipelineJob) => ACTIVE.has(j.status))
        ? 1000
        : false,
  })

  return (
    <div data-testid="jobs" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <h2 className="mb-1 text-xl font-semibold tracking-tight text-ink">
        Processing runs
      </h2>
      <p className="mb-5 text-[0.875rem] leading-relaxed text-muted">
        Every press of Process notes, what it produced, and what it cost.
      </p>

      {isLoading ? (
        <p className="text-[0.8125rem] text-faint">Loading…</p>
      ) : jobs.length === 0 ? (
        <p data-testid="jobs-empty" className="rounded-lg border border-dashed border-line bg-surface p-8 text-center text-[0.875rem] text-faint">
          No run yet. Open a note and press Process notes.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {jobs.map((job) => (
            <li key={job.id}>
              <JobRow
                job={job}
                open={openId === job.id}
                onToggle={() => setOpenId(openId === job.id ? null : job.id)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function JobRow({ job, open, onToggle }: {
  job: PipelineJob
  open: boolean
  onToggle: () => void
}) {
  const [name, when] = job.name.split(' · ')

  return (
    <div
      data-testid={`job-${job.id}`}
      data-status={job.status}
      className="rounded-lg border border-line bg-surface"
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-2 p-3 text-left"
      >
        <StatusDot status={job.status} />
        <span className="min-w-0 flex-1 truncate">
          <span className="text-[0.875rem] font-medium text-ink">{name}</span>
          {when && <span className="ml-2 text-[0.75rem] text-faint">{when}</span>}
        </span>
        <span className="shrink-0 text-[0.75rem] tabular-nums text-muted">
          {job.status === 'running' || job.status === 'queued'
            ? job.stage ?? 'queued'
            : `${job.concepts_created} new`}
        </span>
      </button>

      {open && <JobDetail jobId={job.id} />}
    </div>
  )
}

function JobDetail({ jobId }: { jobId: number }) {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['pipeline-job', jobId],
    queryFn: () => api.job(jobId),
  })

  const retry = useMutation({
    mutationFn: () => api.retryJob(jobId),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['pipeline-jobs'] })
      await qc.invalidateQueries({ queryKey: ['pipeline-job', jobId] })
    },
  })

  if (!data) {
    return <p className="px-3 pb-3 text-[0.75rem] text-faint">Loading…</p>
  }

  const { job, stats } = data

  return (
    <div data-testid="job-detail" className="border-t border-line-soft p-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Blocks" value={job.block_count} />
        <Stat label="Created" value={job.concepts_created} />
        <Stat label="Merged" value={job.concepts_merged} />
        <Stat label="Edges" value={job.edges_proposed} />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="LLM calls" value={stats.llm_calls} />
        <Stat label="In tokens" value={stats.input_tokens.toLocaleString()} />
        <Stat label="Out tokens" value={stats.output_tokens.toLocaleString()} />
        <Stat
          label="Cost"
          value={
            stats.unpriced_calls > 0
              ? `$${stats.estimated_cost_usd.toFixed(4)}+`
              : `$${stats.estimated_cost_usd.toFixed(4)}`
          }
          testid="job-cost"
        />
      </div>

      {stats.unpriced_calls > 0 && (
        <p className="mt-2 text-[0.6875rem] text-faint">
          {stats.unpriced_calls} call(s) used a model with no price on file, so
          the total is a lower bound.
        </p>
      )}

      {job.error_text && (
        <div className="mt-3 rounded-md border border-stale/40 bg-stale-wash p-2.5">
          <p className="text-[0.75rem] font-medium text-ink">
            Failed at {job.stage ?? 'an early stage'}
          </p>
          <p
            data-testid="job-error"
            className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap break-all font-mono text-[0.6875rem] text-ink-soft"
          >
            {job.error_text}
          </p>
          <button
            type="button"
            onClick={() => retry.mutate()}
            disabled={retry.isPending}
            data-testid="job-retry"
            className="mt-2 rounded bg-accent px-2.5 py-1 text-[0.75rem] font-medium text-white transition hover:bg-accent-deep disabled:opacity-50"
          >
            {retry.isPending ? 'Retrying…' : 'Retry'}
          </button>
          <p className="mt-1.5 text-[0.6875rem] text-muted">
            A retry re-runs extraction, which costs tokens again.
          </p>
        </div>
      )}

      {data.runs.length > 0 && (
        <table className="mt-3 w-full text-[0.6875rem]">
          <thead>
            <tr className="text-left text-faint">
              <th className="pb-1 font-medium">Task</th>
              <th className="pb-1 font-medium">Model</th>
              <th className="pb-1 text-right font-medium">In</th>
              <th className="pb-1 text-right font-medium">Out</th>
              <th className="pb-1 text-right font-medium">Cost</th>
            </tr>
          </thead>
          <tbody className="tabular-nums text-ink-soft">
            {data.runs.map((run) => (
              <tr key={run.id} className={run.success ? '' : 'text-stale'}>
                <td className="truncate py-0.5">{run.task.replace(/_/g, ' ')}</td>
                <td className="truncate py-0.5">{run.model}</td>
                <td className="py-0.5 text-right">{run.input_tokens}</td>
                <td className="py-0.5 text-right">{run.output_tokens}</td>
                <td className="py-0.5 text-right">
                  {run.estimated_cost_usd === null
                    ? '—'
                    : `$${run.estimated_cost_usd.toFixed(5)}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function StatusDot({ status }: { status: PipelineJob['status'] }) {
  const colour: Record<string, string> = {
    queued: 'var(--color-faint)',
    running: 'var(--color-accent)',
    succeeded: 'var(--color-mastery-3)',
    failed: 'var(--color-stale)',
    cancelled: 'var(--color-faint)',
  }
  return (
    <span
      className={`size-2 shrink-0 rounded-full ${status === 'running' ? 'animate-pulse' : ''}`}
      style={{ background: colour[status] ?? 'var(--color-line)' }}
      aria-label={status}
    />
  )
}

function Stat({ label, value, testid }: {
  label: string
  value: React.ReactNode
  testid?: string
}) {
  return (
    <div className="rounded-md bg-paper p-2" data-testid={testid}>
      <div className="text-[0.9375rem] font-semibold tabular-nums text-ink">
        {value}
      </div>
      <div className="mt-0.5 text-[0.625rem] text-muted">{label}</div>
    </div>
  )
}
