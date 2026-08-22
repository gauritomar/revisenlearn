import { useQuery } from '@tanstack/react-query'

import { api, type Note, type Resource } from '../lib/api'
import { useUI } from '../store/ui'
import { ResourceRow } from './ResourceList'
import { Calendar } from './Calendar'

/** Spec §14 Dashboard, v1.
 *
 *  Today · Continue learning · Study next · Today's notes · Calendar · Progress.
 *  The review-driven half of "Today" and the Progress charts need review data,
 *  so they fill in at Phase 7 and Phase 9. Explicitly no streaks (spec §14).
 */
const todayISO = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate(),
  ).padStart(2, '0')}`
}

export function Dashboard({ onView }: { onView: (v: string) => void }) {
  const today = todayISO()

  const { data: subjects = [] } = useQuery({ queryKey: ['subjects'], queryFn: api.subjects })
  const { data: studyNext = [] } = useQuery({
    queryKey: ['study-next'],
    queryFn: () => api.studyNext(5),
  })
  const { data: allResources = [] } = useQuery({
    queryKey: ['resources', 'active'],
    queryFn: () => api.resources(),
  })
  const { data: todaysNotes = [] } = useQuery({
    queryKey: ['notes-by-date', today],
    queryFn: () => api.notesByDate(today),
  })

  const setResourceAdd = useUI((s) => s.setResourceAdd)
  const setAddDialog = useUI((s) => s.setAddDialog)

  // §14 "Continue learning (recent resources with progress)".
  const continuing = allResources
    .filter((r) => r.status === 'in_progress' || (r.progress_pct > 0 && r.progress_pct < 100))
    .sort((a, b) => (b.last_opened_at ?? '').localeCompare(a.last_opened_at ?? ''))
    .slice(0, 4)

  const unprocessed = todaysNotes.reduce((n, note) => n + note.counts.new, 0)
  const edited = todaysNotes.reduce((n, note) => n + note.counts.edited, 0)
  const empty = subjects.length === 0 && allResources.length === 0

  return (
    <div data-testid="dashboard" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <div className="mb-5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-xl font-semibold tracking-tight text-ink">Dashboard</h2>
        <span className="text-[0.8125rem] text-muted">
          {new Date().toLocaleDateString(undefined, {
            weekday: 'long', day: 'numeric', month: 'long',
          })}
        </span>
        <button
          type="button"
          onClick={() => setResourceAdd(true)}
          data-testid="dash-add-resource"
          className="ml-auto rounded-md bg-accent px-3 py-1.5 text-[0.8125rem] font-medium text-white transition hover:bg-accent-deep"
        >
          Add resource
        </button>
      </div>

      {empty && (
        <div className="mb-5 rounded-lg border border-dashed border-line bg-surface p-6 text-center">
          <p className="text-[0.875rem] text-muted">Nothing here yet.</p>
          <div className="mt-3 flex flex-wrap justify-center gap-2">
            <button
              type="button"
              onClick={() => setAddDialog(true)}
              data-testid="dashboard-add-first"
              className="rounded-md border border-line px-3 py-1.5 text-[0.8125rem] text-ink transition hover:border-accent hover:text-accent-deep"
            >
              Add your first subject
            </button>
            <button
              type="button"
              onClick={() => setResourceAdd(true)}
              className="rounded-md border border-line px-3 py-1.5 text-[0.8125rem] text-ink transition hover:border-accent hover:text-accent-deep"
            >
              Add a resource
            </button>
          </div>
        </div>
      )}

      {/* Today */}
      <Section title="Today" testid="dash-today">
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Due to review" value="—" hint="Phase 7" />
          <Stat label="New blocks" value={unprocessed} />
          <Stat label="Edited blocks" value={edited} tone={edited > 0 ? 'stale' : undefined} />
        </div>
      </Section>

      {/* Continue learning */}
      <Section
        title="Continue learning"
        testid="dash-continue-learning"
        action={
          allResources.length > 0
            ? { label: 'All resources', onClick: () => onView('Resources') }
            : undefined
        }
      >
        {continuing.length === 0 ? (
          <Empty>No resources in progress.</Empty>
        ) : (
          <ResourceCards resources={continuing} />
        )}
      </Section>

      {/* Study next */}
      <Section title="Study next" testid="dash-study-next">
        {studyNext.length === 0 ? (
          <Empty>Nothing queued.</Empty>
        ) : (
          <ResourceCards resources={studyNext} />
        )}
      </Section>

      {/* Today's notes */}
      <Section title="Today's notes" testid="dash-todays-notes">
        {todaysNotes.length === 0 ? (
          <Empty>Nothing written today.</Empty>
        ) : (
          <ul className="space-y-1">
            {todaysNotes.map((note) => (
              <li key={note.id}>
                <NoteLine note={note} />
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Calendar" testid="dash-calendar">
        <Calendar />
      </Section>

      <Section title="Progress" testid="dash-progress">
        <Empty>
          Concepts, reviews, mastery distribution and retention appear once
          review data exists.
        </Empty>
      </Section>
    </div>
  )
}

function ResourceCards({ resources }: { resources: Resource[] }) {
  const openResource = useUI((s) => s.openResource)
  return (
    <ul className="space-y-1.5">
      {resources.map((r) => (
        <li key={r.id}>
          <button
            type="button"
            onClick={() => openResource(r.id)}
            data-testid={`resource-${r.id}`}
            className="w-full rounded-lg border border-line bg-paper p-2.5 text-left transition hover:border-faint"
          >
            <ResourceRow resource={r} />
          </button>
        </li>
      ))}
    </ul>
  )
}

function NoteLine({ note }: { note: Note }) {
  const openSubtopic = useUI((s) => s.openSubtopic)
  const openResource = useUI((s) => s.openResource)

  return (
    <button
      type="button"
      data-testid={`todays-note-${note.id}`}
      onClick={() =>
        note.resource_id
          ? openResource(note.resource_id)
          : openSubtopic(note.subtopic_id ?? -1, note.id)
      }
      className="flex w-full items-baseline gap-2 rounded-md px-2 py-1.5 text-left transition hover:bg-sunken"
    >
      <span className="min-w-0 flex-1 truncate text-[0.8125rem] text-ink">{note.title}</span>
      <span className="shrink-0 text-[0.6875rem] tabular-nums text-faint">
        {note.blocks.length} {note.blocks.length === 1 ? 'block' : 'blocks'}
      </span>
    </button>
  )
}

function Section({ title, testid, action, children }: {
  title: string
  testid: string
  action?: { label: string; onClick: () => void }
  children: React.ReactNode
}) {
  return (
    <section data-testid={testid} className="mb-3 rounded-lg border border-line bg-surface p-4">
      <div className="mb-2.5 flex items-baseline gap-2">
        <h3 className="text-[0.8125rem] font-semibold tracking-tight text-ink">{title}</h3>
        {action && (
          <button
            type="button"
            onClick={action.onClick}
            className="ml-auto text-[0.75rem] text-muted transition hover:text-accent-deep"
          >
            {action.label}
          </button>
        )}
      </div>
      {children}
    </section>
  )
}

function Stat({ label, value, hint, tone }: {
  label: string
  value: React.ReactNode
  hint?: string
  tone?: 'stale'
}) {
  return (
    <div className="rounded-md bg-paper p-2.5">
      <div
        className={`text-lg font-semibold tabular-nums ${
          tone === 'stale' ? 'text-stale' : 'text-ink'
        }`}
      >
        {value}
      </div>
      <div className="mt-0.5 text-[0.6875rem] leading-tight text-muted">{label}</div>
      {hint && <div className="text-[0.625rem] text-faint">{hint}</div>}
    </div>
  )
}

const Empty = ({ children }: { children: React.ReactNode }) => (
  <p className="text-[0.8125rem] leading-relaxed text-faint">{children}</p>
)
