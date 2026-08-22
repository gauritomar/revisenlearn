import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Subject } from '../lib/api'
import { useUI } from '../store/ui'

/** Spec §14 — left sidebar: Subjects → Topics → Subtopics, collapsible,
 *  state persisted. Three fixed levels, no arbitrary nesting (§3 [LOCKED]). */
export function LeftSidebar() {
  const { data: subjects = [], isLoading } = useQuery({
    queryKey: ['subjects'],
    queryFn: api.subjects,
  })
  const setAddDialog = useUI((s) => s.setAddDialog)

  return (
    <aside
      data-testid="left-sidebar"
      className="flex h-full w-60 shrink-0 flex-col border-r border-line bg-paper"
    >
      <div className="flex h-11 shrink-0 items-center justify-between gap-2 border-b border-line-soft px-3">
        <span className="text-[0.6875rem] font-semibold uppercase tracking-[0.09em] text-muted">
          Subjects
        </span>
        <button
          type="button"
          onClick={() => setAddDialog(true)}
          data-testid="sidebar-add"
          aria-label="Add subject, topic or subtopic"
          title="Add subject, topic or subtopic"
          className="grid size-6 place-items-center rounded-md border border-line bg-surface text-muted transition hover:border-accent hover:text-accent-deep"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M6 2v8M2 6h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-2">
        {isLoading ? (
          <p className="px-2 py-1 text-[0.8125rem] text-faint">Loading…</p>
        ) : subjects.length === 0 ? (
          <p data-testid="sidebar-empty" className="px-2 py-3 text-[0.8125rem] leading-relaxed text-faint">
            No subjects yet. Press <span className="font-medium text-muted">+</span> to add one.
          </p>
        ) : (
          <ul data-testid="subject-tree" className="space-y-0.5">
            {subjects.map((s) => <SubjectRow key={s.id} subject={s} />)}
          </ul>
        )}
      </div>
    </aside>
  )
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true"
      className={`shrink-0 text-faint transition-transform ${open ? 'rotate-90' : ''}`}
    >
      <path d="m3.5 2 3.5 3-3.5 3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function SubjectRow({ subject }: { subject: Subject }) {
  const expanded = useUI((s) => s.expandedSubjects.includes(subject.id))
  const toggleSubject = useUI((s) => s.toggleSubject)

  return (
    <li>
      <button
        type="button"
        onClick={() => toggleSubject(subject.id)}
        data-testid={`subject-${subject.name}`}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[0.8125rem] font-medium text-ink transition hover:bg-sunken"
      >
        <Chevron open={expanded} />
        <span
          className="size-2 shrink-0 rounded-full"
          style={{ background: subject.colour ?? 'var(--color-faint)' }}
          aria-hidden="true"
        />
        <span className="truncate">{subject.name}</span>
      </button>

      {expanded && (
        <ul className="ml-3 border-l border-line-soft pl-1.5">
          {subject.topics.length === 0 ? (
            <li className="px-2 py-1 text-[0.75rem] text-faint">No topics</li>
          ) : (
            subject.topics.map((t) => <TopicRow key={t.id} topic={t} />)
          )}
        </ul>
      )}
    </li>
  )
}

function TopicRow({ topic }: { topic: Subject['topics'][number] }) {
  const expanded = useUI((s) => s.expandedTopics.includes(topic.id))
  const toggleTopic = useUI((s) => s.toggleTopic)

  return (
    <li>
      <button
        type="button"
        onClick={() => toggleTopic(topic.id)}
        data-testid={`topic-${topic.name}`}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[0.8125rem] text-ink-soft transition hover:bg-sunken"
      >
        <Chevron open={expanded} />
        <span className="truncate">{topic.name}</span>
      </button>

      {expanded && (
        <ul className="ml-3 border-l border-line-soft pl-1.5">
          {topic.subtopics.length === 0 ? (
            <li className="px-2 py-1 text-[0.75rem] text-faint">No subtopics</li>
          ) : (
            topic.subtopics.map((st) => <SubtopicRow key={st.id} id={st.id} name={st.name} />)
          )}
        </ul>
      )}
    </li>
  )
}

function SubtopicRow({ id, name }: { id: number; name: string }) {
  const active = useUI((s) => s.activeSubtopicId === id)
  const openSubtopic = useUI((s) => s.openSubtopic)
  const qc = useQueryClient()

  /** Spec §4.1 — clicking a subtopic opens today's note, created on the spot
   *  if it does not exist. */
  async function open() {
    const note = await api.ensureNote(id)
    qc.setQueryData(['note', note.id], note)
    openSubtopic(id, note.id)
  }

  return (
    <li>
      <button
        type="button"
        onClick={open}
        data-testid={`subtopic-${name}`}
        className={[
          'flex w-full items-center gap-1.5 rounded-md py-1.5 pl-4 pr-2 text-left text-[0.8125rem] transition',
          active ? 'bg-accent-wash font-medium text-accent-deep' : 'text-muted hover:bg-sunken hover:text-ink',
        ].join(' ')}
      >
        <span className="truncate">{name}</span>
      </button>
    </li>
  )
}
