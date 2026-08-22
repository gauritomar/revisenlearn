import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Subject } from '../lib/api'
import { useOpenLesson } from '../lib/openLesson'
import { useUI } from '../store/ui'

/** Quick-add (consolidated addendum §5).
 *
 *  "a quick-add entry point (a "+" fixed at the top of the sidebar, or
 *  reachable via ⌘K) that opens a small picker — choose the parent
 *  (search/select any existing Subject, Topic, or Subtopic), type the new
 *  item's name, done. This must work without first expanding/collapsing down
 *  through the tree to reach the right spot."
 *
 *  So the parent is *searched*, not navigated to, and what gets created is
 *  implied by what was picked: a Subject at the top level, a Topic under a
 *  Subject, a Subtopic or Lesson under a Topic, a Lesson under a Subtopic.
 *  Three fixed levels of hierarchy still hold (spec §3 **[LOCKED]**).
 */
type Parent =
  | { kind: 'root'; id: null; label: string; path: string }
  | { kind: 'subject'; id: number; label: string; path: string }
  | { kind: 'topic'; id: number; label: string; path: string; subjectId: number }
  | { kind: 'subtopic'; id: number; label: string; path: string; topicId: number }

const ROOT: Parent = { kind: 'root', id: null, label: 'Top level', path: 'a new subject' }

function parentsOf(subjects: Subject[]): Parent[] {
  const out: Parent[] = [ROOT]
  for (const subject of subjects) {
    out.push({ kind: 'subject', id: subject.id, label: subject.name, path: subject.name })
    for (const topic of subject.topics) {
      out.push({
        kind: 'topic', id: topic.id, label: topic.name,
        path: `${subject.name} › ${topic.name}`, subjectId: subject.id,
      })
      for (const subtopic of topic.subtopics) {
        out.push({
          kind: 'subtopic', id: subtopic.id, label: subtopic.name,
          path: `${subject.name} › ${topic.name} › ${subtopic.name}`,
          topicId: topic.id,
        })
      }
    }
  }
  return out
}

/** What a pick can create. A Topic can hold either, so the user chooses. */
function creatable(parent: Parent): Array<'subject' | 'topic' | 'subtopic' | 'lesson'> {
  if (parent.kind === 'root') return ['subject']
  if (parent.kind === 'subject') return ['topic']
  if (parent.kind === 'topic') return ['subtopic', 'lesson']
  return ['lesson']
}

export function AddDialog() {
  const open = useUI((s) => s.addDialogOpen)
  const setOpen = useUI((s) => s.setAddDialog)
  const toggleSubject = useUI((s) => s.toggleSubject)
  const toggleTopic = useUI((s) => s.toggleTopic)
  const toggleSubtopic = useUI((s) => s.toggleSubtopic)
  const qc = useQueryClient()
  const openLesson = useOpenLesson()
  const seed = useUI((s) => s.addSeed)

  const { data: subjects = [] } = useQuery({ queryKey: ['subjects'], queryFn: api.subjects })

  const [query, setQuery] = useState('')
  const [parent, setParent] = useState<Parent>(ROOT)
  const [kind, setKind] = useState<'subject' | 'topic' | 'subtopic' | 'lesson'>('subject')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const nameRef = useRef<HTMLInputElement>(null)

  const parents = useMemo(() => parentsOf(subjects), [subjects])
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    const pool = q
      ? parents.filter((p) => p.path.toLowerCase().includes(q) || p.label.toLowerCase().includes(q))
      : parents
    return pool.slice(0, 8)
  }, [parents, query])

  useEffect(() => {
    if (!open) {
      setQuery(''); setParent(ROOT); setKind('subject'); setName(''); setError(null)
      return
    }
    // Opened from ⌘K: keep what was already typed as the new item's name.
    setName(seed)
    const id = window.setTimeout(() => nameRef.current?.select(), 0)
    return () => window.clearTimeout(id)
  }, [open, seed])

  // Keep the kind honest when the parent changes under it.
  useEffect(() => {
    const options = creatable(parent)
    setKind((current) => (options.includes(current) ? current : options[0]))
  }, [parent])

  if (!open) return null

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const title = name.trim()
    if (!title || busy) return
    setBusy(true)
    setError(null)
    try {
      let createdLessonId: number | null = null

      if (kind === 'subject') {
        const subject = await api.createSubject(title)
        toggleSubject(subject.id)
      } else if (kind === 'topic' && parent.kind === 'subject') {
        const topic = await api.createTopic(parent.id, title)
        reveal(parent.id, topic.id, null)
      } else if (kind === 'subtopic' && parent.kind === 'topic') {
        const subtopic = await api.createSubtopic(parent.id, title)
        reveal(parent.subjectId, parent.id, subtopic.id)
      } else if (kind === 'lesson' && parent.kind === 'topic') {
        const lesson = await api.createLesson({ topic_id: parent.id, name: title })
        createdLessonId = lesson.id
        reveal(parent.subjectId, parent.id, null)
      } else if (kind === 'lesson' && parent.kind === 'subtopic') {
        const lesson = await api.createLesson({
          topic_id: parent.topicId, subtopic_id: parent.id, name: title,
        })
        createdLessonId = lesson.id
        reveal(null, parent.topicId, parent.id)
      }

      await qc.invalidateQueries({ queryKey: ['subjects'] })
      await qc.invalidateQueries({ queryKey: ['roadmap'] })
      setOpen(false)
      // A new lesson is a place to write, so go there (§3).
      if (createdLessonId !== null) await openLesson(createdLessonId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save')
    } finally {
      setBusy(false)
    }
  }

  /** Expand the ancestors so what was just created is actually visible. */
  function reveal(subjectId: number | null, topicId: number | null, subtopicId: number | null) {
    const state = useUI.getState()
    if (subjectId !== null && !state.expandedSubjects.includes(subjectId)) toggleSubject(subjectId)
    if (topicId !== null && !state.expandedTopics.includes(topicId)) toggleTopic(topicId)
    if (subtopicId !== null && !state.expandedSubtopics.includes(subtopicId)) {
      toggleSubtopic(subtopicId)
    }
  }

  const options = creatable(parent)

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-ink/15 px-4 pt-[14vh] backdrop-blur-[2px]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false) }}
      role="presentation"
    >
      <form
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-label="Add to the tree"
        data-testid="add-dialog"
        className="w-full max-w-md rounded-xl border border-line bg-surface p-4 shadow-xl"
      >
        <h2 className="text-[0.9375rem] font-semibold tracking-tight text-ink">Add to the tree</h2>
        <p className="mt-1 text-[0.8125rem] leading-relaxed text-muted">
          Pick where it goes, give it a name. No need to expand anything first.
        </p>

        <label className="mt-4 block">
          <span className="mb-1 block text-[0.75rem] font-medium text-ink-soft">Name</span>
          <input
            ref={nameRef}
            value={name}
            onChange={(e) => setName(e.target.value)}
            data-testid="input-name"
            placeholder="Hybrid search"
            className="w-full rounded-md border border-line bg-paper px-2.5 py-1.5 text-[0.875rem] text-ink outline-none transition placeholder:text-faint focus:border-accent"
          />
        </label>

        <div className="mt-3">
          <span className="mb-1 flex items-baseline gap-2 text-[0.75rem] font-medium text-ink-soft">
            Inside
            <span data-testid="add-parent" className="font-normal text-faint">{parent.path}</span>
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            data-testid="input-parent-search"
            placeholder="Search subjects, topics, subtopics…"
            className="w-full rounded-md border border-line bg-paper px-2.5 py-1.5 text-[0.8125rem] text-ink outline-none transition placeholder:text-faint focus:border-accent"
          />
          <ul
            data-testid="add-parent-options"
            className="mt-1 max-h-40 overflow-y-auto rounded-md border border-line-soft"
          >
            {matches.length === 0 ? (
              <li className="px-2.5 py-2 text-[0.75rem] text-faint">Nothing matches.</li>
            ) : (
              matches.map((option) => {
                const selected = option.kind === parent.kind && option.id === parent.id
                return (
                  <li key={`${option.kind}-${option.id}`}>
                    <button
                      type="button"
                      onClick={() => setParent(option)}
                      data-testid={
                        option.kind === 'root' ? 'add-parent-root'
                          : `add-parent-${option.kind}-${option.id}`
                      }
                      className={[
                        'flex w-full items-baseline gap-2 px-2.5 py-1.5 text-left text-[0.8125rem] transition',
                        selected ? 'bg-accent-wash text-accent-deep' : 'text-ink hover:bg-sunken',
                      ].join(' ')}
                    >
                      <span className="min-w-0 flex-1 truncate">{option.path}</span>
                      <span className="shrink-0 text-[0.625rem] uppercase tracking-wide text-faint">
                        {option.kind === 'root' ? 'new subject' : option.kind}
                      </span>
                    </button>
                  </li>
                )
              })
            )}
          </ul>
        </div>

        {/* Only a Topic is ambiguous — it can hold subtopics and lessons. */}
        {options.length > 1 && (
          <div className="mt-3 flex items-center gap-1.5" data-testid="add-kind">
            {options.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setKind(option)}
                data-testid={`add-kind-${option}`}
                aria-pressed={kind === option}
                className={[
                  'rounded-md border px-2 py-1 text-[0.75rem] transition',
                  kind === option
                    ? 'border-accent bg-accent-wash text-accent-deep'
                    : 'border-line text-muted hover:text-ink',
                ].join(' ')}
              >
                {option === 'subtopic' ? 'Subtopic' : 'Lesson'}
              </button>
            ))}
          </div>
        )}

        {error && (
          <p data-testid="add-dialog-error" className="mt-3 text-[0.8125rem] text-stale">
            {error}
          </p>
        )}

        <div className="mt-5 flex items-center justify-between gap-2">
          <span className="text-[0.6875rem] text-faint">
            Adding a <span className="text-muted">{kind}</span>
          </span>
          <span className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-md px-3 py-1.5 text-[0.8125rem] text-muted transition hover:bg-sunken hover:text-ink"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!name.trim() || busy}
              data-testid="add-dialog-submit"
              className="rounded-md bg-accent px-3.5 py-1.5 text-[0.8125rem] font-medium text-white transition hover:bg-accent-deep disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? 'Adding…' : 'Add'}
            </button>
          </span>
        </div>
      </form>
    </div>
  )
}
