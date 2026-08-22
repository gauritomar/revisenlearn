import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useUI } from '../store/ui'

/** Spec §14 Dashboard. Phase 1 renders the real sections with honest empty
 *  states; each fills in at the phase that produces its data. Explicitly no
 *  streaks (spec §14). */
const SECTIONS: Array<{ title: string; empty: string; phase: number }> = [
  { title: 'Today', empty: 'No due items, new concepts or unprocessed blocks.', phase: 7 },
  { title: 'Continue learning', empty: 'No resources in progress.', phase: 2 },
  { title: 'Study next', empty: 'Nothing queued.', phase: 2 },
  { title: "Today's notes", empty: 'Nothing written today.', phase: 2 },
]

export function Dashboard() {
  const { data: subjects = [] } = useQuery({ queryKey: ['subjects'], queryFn: api.subjects })
  const setAddDialog = useUI((s) => s.setAddDialog)

  const topicCount = subjects.reduce((n, s) => n + s.topics.length, 0)
  const subtopicCount = subjects.reduce(
    (n, s) => n + s.topics.reduce((m, t) => m + t.subtopics.length, 0),
    0,
  )

  return (
    <div data-testid="dashboard" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <div className="mb-6">
        <h2 className="text-xl font-semibold tracking-tight text-ink">Dashboard</h2>
        <p className="mt-1 text-[0.875rem] leading-relaxed text-muted">
          {subjects.length === 0
            ? 'Nothing here yet. Add a subject to begin.'
            : `${subjects.length} subjects · ${topicCount} topics · ${subtopicCount} subtopics`}
        </p>
      </div>

      {subjects.length === 0 && (
        <button
          type="button"
          onClick={() => setAddDialog(true)}
          data-testid="dashboard-add-first"
          className="mb-6 w-full rounded-lg border border-dashed border-line bg-surface px-4 py-8 text-center text-[0.875rem] text-muted transition hover:border-accent hover:text-accent-deep"
        >
          Add your first subject
        </button>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {SECTIONS.map((s) => (
          <section
            key={s.title}
            data-testid={`dash-${s.title.toLowerCase().replace(/[^a-z]+/g, '-')}`}
            className="rounded-lg border border-line bg-surface p-4"
          >
            <h3 className="text-[0.8125rem] font-semibold tracking-tight text-ink">{s.title}</h3>
            <p className="mt-2 text-[0.8125rem] leading-relaxed text-faint">{s.empty}</p>
          </section>
        ))}
      </div>

      <section className="mt-3 rounded-lg border border-line bg-surface p-4">
        <h3 className="text-[0.8125rem] font-semibold tracking-tight text-ink">Progress</h3>
        <p className="mt-2 text-[0.8125rem] leading-relaxed text-faint">
          Concepts, reviews, mastery distribution and retention appear once
          review data exists.
        </p>
      </section>
    </div>
  )
}
