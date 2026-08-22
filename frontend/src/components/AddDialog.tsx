import { forwardRef, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, createBranch } from '../lib/api'
import { useUI } from '../store/ui'

/** One dialog for the whole branch: Subject, then Topic, then Subtopic
 *  (spec §3 — three fixed levels). Topic and Subtopic are optional, so this
 *  also covers "just add a subject". Names that already exist are reused rather
 *  than duplicated. */
export function AddDialog() {
  const open = useUI((s) => s.addDialogOpen)
  const setOpen = useUI((s) => s.setAddDialog)
  const toggleSubject = useUI((s) => s.toggleSubject)
  const toggleTopic = useUI((s) => s.toggleTopic)
  const qc = useQueryClient()

  const { data: subjects = [] } = useQuery({ queryKey: ['subjects'], queryFn: api.subjects })

  const [subject, setSubject] = useState('')
  const [topic, setTopic] = useState('')
  const [subtopic, setSubtopic] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const firstRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) {
      setSubject('')
      setTopic('')
      setSubtopic('')
      setError(null)
      return
    }
    const id = window.setTimeout(() => firstRef.current?.focus(), 0)
    return () => window.clearTimeout(id)
  }, [open])

  if (!open) return null

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!subject.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      const created = await createBranch(subjects, subject, topic, subtopic)
      await qc.invalidateQueries({ queryKey: ['subjects'] })
      // Reveal what was just created rather than leaving it collapsed.
      const state = useUI.getState()
      if (!state.expandedSubjects.includes(created.subjectId)) toggleSubject(created.subjectId)
      if (created.topicId && !state.expandedTopics.includes(created.topicId)) {
        toggleTopic(created.topicId)
      }
      setOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-ink/15 px-4 pt-[14vh] backdrop-blur-[2px]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) setOpen(false)
      }}
      role="presentation"
    >
      <form
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-label="Add subject, topic and subtopic"
        data-testid="add-dialog"
        className="w-full max-w-md rounded-xl border border-line bg-surface p-4 shadow-xl"
      >
        <h2 className="text-[0.9375rem] font-semibold tracking-tight text-ink">Add to the tree</h2>
        <p className="mt-1 text-[0.8125rem] leading-relaxed text-muted">
          Subject is required. Topic and Subtopic are optional. Existing names
          are reused, not duplicated.
        </p>

        <div className="mt-4 space-y-3">
          <Field
            ref={firstRef}
            label="Subject"
            testid="input-subject"
            value={subject}
            onChange={setSubject}
            placeholder="GenAI"
            required
          />
          <Field
            label="Topic"
            testid="input-topic"
            value={topic}
            onChange={setTopic}
            placeholder="Retrieval"
          />
          <Field
            label="Subtopic"
            testid="input-subtopic"
            value={subtopic}
            onChange={setSubtopic}
            placeholder="Hybrid search"
            disabled={!topic.trim()}
            hint={!topic.trim() ? 'Needs a topic first' : undefined}
          />
        </div>

        {error && (
          <p data-testid="add-dialog-error" className="mt-3 text-[0.8125rem] text-stale">
            {error}
          </p>
        )}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="rounded-md px-3 py-1.5 text-[0.8125rem] text-muted transition hover:bg-sunken hover:text-ink"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!subject.trim() || busy}
            data-testid="add-dialog-submit"
            className="rounded-md bg-accent px-3.5 py-1.5 text-[0.8125rem] font-medium text-white transition hover:bg-accent-deep disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? 'Adding…' : 'Add'}
          </button>
        </div>
      </form>
    </div>
  )
}

type FieldProps = {
  label: string
  testid: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  required?: boolean
  disabled?: boolean
  hint?: string
}

const Field = forwardRef<HTMLInputElement, FieldProps>(function Field(
  { label, testid, value, onChange, placeholder, required, disabled, hint },
  ref,
) {
  return (
    <label className="block">
      <span className="mb-1 flex items-baseline gap-2 text-[0.75rem] font-medium text-ink-soft">
        {label}
        {hint && <span className="text-[0.6875rem] font-normal text-faint">{hint}</span>}
      </span>
      <input
        ref={ref}
        value={value}
        required={required}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        data-testid={testid}
        className="w-full rounded-md border border-line bg-paper px-2.5 py-1.5 text-[0.875rem] text-ink outline-none transition placeholder:text-faint focus:border-accent focus:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
      />
    </label>
  )
})
