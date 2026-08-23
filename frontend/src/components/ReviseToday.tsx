import { useMutation, useQuery } from '@tanstack/react-query'

import { api, type RecallGroup } from '../lib/api'
import { useUI } from '../store/ui'

/** What to revise today, and the practice set for it.
 *
 *  "I wanted the spaced repetition algorithms to remind me that today you
 *  have to revise what you studied 1/3/10 etc days ago. And I should have
 *  their corresponding practice MCQ sets ready to open and practice. I should
 *  also be able to look at my progress on the MCQs side by side."
 *
 *  FSRS decides *when* (§9.3). This says *what*, in the terms the work was
 *  done in — the day it was written — and puts the questions and the score
 *  for that material in the same row.
 */
export function ReviseToday({ onView }: { onView?: (view: string) => void }) {
  const { data, isLoading } = useQuery({ queryKey: ['recall'], queryFn: api.recall })

  if (isLoading) {
    return <p className="text-[0.8125rem] text-faint">Loading…</p>
  }

  if (!data || data.groups.length === 0) {
    return (
      <p data-testid="revise-empty" className="text-[0.8125rem] leading-relaxed text-faint">
        Nothing is due. Concepts come back on their own schedule once notes
        have been processed — a day later, then three, then ten.
      </p>
    )
  }

  return (
    <div data-testid="revise-today" className="space-y-2">
      <p className="text-[0.8125rem] text-muted">
        {data.total_due} concept{data.total_due === 1 ? '' : 's'} due, from{' '}
        {data.groups.length} day{data.groups.length === 1 ? '' : 's'} of notes.
      </p>
      {data.groups.map((group) => (
        <GroupRow key={group.studied_on ?? 'unknown'} group={group} onView={onView} />
      ))}
    </div>
  )
}

function whenLabel(group: RecallGroup): string {
  if (group.days_ago === null) return 'From notes with no date'
  if (group.days_ago === 0) return 'Studied today'
  if (group.days_ago === 1) return 'Studied yesterday'
  return `Studied ${group.days_ago} days ago`
}

function GroupRow({ group, onView }: {
  group: RecallGroup
  onView?: (view: string) => void
}) {
  const setPendingPractice = useUI((s) => s.setPendingPractice)

  const practise = useMutation({
    // Scoped to exactly this day's concepts, so "revise Tuesday" is a session
    // rather than a filter the user has to rebuild.
    mutationFn: () =>
      api.startPractice(Math.min(20, Math.max(5, group.mcqs_available)), {
        concept_ids: group.concept_ids,
      }),
    onSuccess: (session) => {
      setPendingPractice(session.id)
      onView?.('Practice')
    },
  })

  return (
    <section
      data-testid={`revise-group-${group.studied_on ?? 'unknown'}`}
      className="rounded-lg border border-line bg-surface p-3"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h4 className="text-[0.8125rem] font-medium text-ink">{whenLabel(group)}</h4>
        <span className="text-[0.75rem] text-muted">
          {group.due_count} concept{group.due_count === 1 ? '' : 's'} due
        </span>

        {/* Progress sits next to the work, not on another screen. */}
        <span className="ml-auto flex items-center gap-2 text-[0.75rem]">
          {group.answered > 0 ? (
            <span data-testid="revise-progress" className="tabular-nums text-muted">
              {group.correct}/{group.answered} correct
              {group.accuracy !== null && (
                <span className={group.accuracy >= 70 ? ' text-emerald-700' : ' text-amber-700'}>
                  {' '}({group.accuracy}%)
                </span>
              )}
            </span>
          ) : (
            <span className="text-faint">not practised yet</span>
          )}

          <button
            type="button"
            onClick={() => practise.mutate()}
            disabled={group.mcqs_available === 0 || practise.isPending}
            data-testid={`practise-${group.studied_on ?? 'unknown'}`}
            title={group.mcqs_available === 0
              ? 'No questions for this material yet'
              : `Practise ${group.mcqs_available} question(s)`}
            className="rounded-md bg-accent px-2.5 py-1 text-[0.75rem] font-medium text-white transition hover:bg-accent-deep disabled:cursor-not-allowed disabled:opacity-40"
          >
            {practise.isPending ? 'Starting…' : `Practise ${group.mcqs_available}`}
          </button>
        </span>
      </div>

      <ul className="mt-2 space-y-0.5">
        {group.concepts.map((concept) => (
          <li
            key={concept.id}
            className="flex items-baseline gap-2 text-[0.75rem]"
          >
            <span className="min-w-0 flex-1 truncate text-ink-soft">{concept.name}</span>
            <span className="shrink-0 tabular-nums text-faint">
              {concept.answered > 0
                ? `${concept.correct}/${concept.answered}`
                : `${concept.mcqs_available} q`}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
