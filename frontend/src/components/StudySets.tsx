import { useQuery } from '@tanstack/react-query'

import { api, type StudySet } from '../lib/api'
import { Waiting } from './Waiting'

/** Ready-made sets, one per place you have studied.
 *
 *  "Let's create both MCQs and Revision sets subtopic wise because otherwise
 *  I don't know what I'm in for … based on my recency of notes."
 *
 *  Most recent first: the material you were just in is the material worth
 *  consolidating, and it is also the one you can judge the questions on.
 */
export function StudySets({ kind, onPick, busyFor }: {
  kind: 'practice' | 'revision'
  onPick: (set: StudySet) => void
  busyFor?: number | null
}) {
  const { data, isLoading } = useQuery({
    queryKey: [kind === 'practice' ? 'practice-sets' : 'revision-sets'],
    queryFn: kind === 'practice'
      ? async () => (await api.practiceSets()).sets
      : async () => (await api.revisionSets()).sets,
  })

  if (isLoading) return <Waiting what="Looking at what you have studied…" />

  const sets = data ?? []
  if (sets.length === 0) {
    return (
      <p data-testid={`${kind}-sets-empty`} className="mt-4 text-[0.8125rem] leading-relaxed text-faint">
        Nothing to work from yet. Write some notes and press Process notes —
        sets appear per lesson and subtopic once there are concepts in them.
      </p>
    )
  }

  return (
    <ul className="mt-3 space-y-1.5" data-testid={`${kind}-sets`}>
      {sets.map((set) => (
        <li key={`${set.kind}-${set.id}`}>
          <button
            type="button"
            onClick={() => onPick(set)}
            disabled={busyFor === set.id ||
              (kind === 'practice' ? set.mcqs_available === 0 : set.due_count === 0)}
            data-testid={`set-${set.kind}-${set.id}`}
            className="w-full rounded-lg border border-line bg-surface p-3 text-left transition hover:border-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="text-[0.875rem] font-medium text-ink">{set.name}</span>
              {set.path && (
                <span className="text-[0.6875rem] text-faint">{set.path}</span>
              )}
              <span className="ml-auto text-[0.75rem] tabular-nums text-muted">
                {kind === 'practice'
                  ? `${set.mcqs_available} question${set.mcqs_available === 1 ? '' : 's'}`
                  : `${set.due_count} due`}
              </span>
            </div>

            <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-[0.75rem] text-faint">
              <span>
                {set.concept_count} concept{set.concept_count === 1 ? '' : 's'}
              </span>
              <span aria-hidden="true">·</span>
              <span>{whenLabel(set)}</span>
              {set.answered > 0 && (
                <>
                  <span aria-hidden="true">·</span>
                  <span className={set.accuracy !== null && set.accuracy >= 70
                    ? 'text-emerald-700' : 'text-amber-700'}>
                    {set.correct}/{set.answered} correct
                  </span>
                </>
              )}
              {busyFor === set.id && <span className="ml-auto">starting…</span>}
            </div>
          </button>
        </li>
      ))}
    </ul>
  )
}

function whenLabel(set: StudySet): string {
  if (set.days_ago === null) return 'no date'
  if (set.days_ago === 0) return 'written today'
  if (set.days_ago === 1) return 'written yesterday'
  return `written ${set.days_ago} days ago`
}
