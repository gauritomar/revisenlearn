import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Placement, type Subject } from '../lib/api'
import { useUI } from '../store/ui'

/** Spec §5.1 [LOCKED] — "Adding a resource must take under five seconds: a
 *  single input where the user pastes a URL or types a title, with
 *  subject/topic pickers that default to the last-used values."
 *
 *  So: one focused input, Enter saves. The pickers are pre-filled and tucked
 *  below; the title probe runs in the background and never blocks the save.
 */
const looksLikeUrl = (v: string) => /^https?:\/\/\S+$/i.test(v.trim())

export function ResourceQuickAdd() {
  const open = useUI((s) => s.resourceAddOpen)
  const setOpen = useUI((s) => s.setResourceAdd)
  const qc = useQueryClient()

  const { data: subjects = [] } = useQuery({ queryKey: ['subjects'], queryFn: api.subjects })
  const { data: lastUsed } = useQuery({ queryKey: ['last-used'], queryFn: api.lastUsed })

  const [value, setValue] = useState('')
  const [title, setTitle] = useState<string | null>(null)
  const [probing, setProbing] = useState(false)
  const [placement, setPlacement] = useState<Placement>({})
  const inputRef = useRef<HTMLInputElement>(null)
  const probeSeq = useRef(0)

  useEffect(() => {
    if (!open) {
      setValue('')
      setTitle(null)
      setProbing(false)
      return
    }
    setPlacement(lastUsed ?? {})
    const id = window.setTimeout(() => inputRef.current?.focus(), 0)
    return () => window.clearTimeout(id)
  }, [open, lastUsed])

  // Probe the page title in the background. A stale response must never
  // overwrite a newer one, hence the sequence guard.
  useEffect(() => {
    if (!open || !looksLikeUrl(value)) {
      setTitle(null)
      setProbing(false)
      return
    }
    const seq = ++probeSeq.current
    setProbing(true)
    const timer = window.setTimeout(async () => {
      try {
        const probed = await api.probeTitle(value.trim())
        if (seq === probeSeq.current) setTitle(probed.title)
      } catch {
        if (seq === probeSeq.current) setTitle(null)
      } finally {
        if (seq === probeSeq.current) setProbing(false)
      }
    }, 350)
    return () => window.clearTimeout(timer)
  }, [value, open])

  const create = useMutation({
    mutationFn: async () => {
      const raw = value.trim()
      const isUrl = looksLikeUrl(raw)
      return api.createResource({
        url: isUrl ? raw : null,
        // Fail silently to the raw URL if the probe found nothing (§5.1).
        title: isUrl ? title ?? raw : raw,
        ...placement,
      })
    },
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['resources'] }),
        qc.invalidateQueries({ queryKey: ['study-next'] }),
        qc.invalidateQueries({ queryKey: ['last-used'] }),
      ])
      setOpen(false)
    },
  })

  if (!open) return null

  const topics = subjects.find((s) => s.id === placement.subject_id)?.topics ?? []
  const subtopics = topics.find((t) => t.id === placement.topic_id)?.subtopics ?? []

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-ink/15 px-4 pt-[14vh] backdrop-blur-[2px]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false) }}
      role="presentation"
    >
      <form
        role="dialog"
        aria-modal="true"
        aria-label="Add a resource"
        data-testid="resource-add"
        className="w-full max-w-lg rounded-xl border border-line bg-surface p-4 shadow-xl"
        onSubmit={(e) => { e.preventDefault(); if (value.trim()) create.mutate() }}
      >
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Paste a link, or type what to study"
          aria-label="Link or title"
          data-testid="resource-input"
          className="h-11 w-full rounded-md border border-line bg-paper px-3 text-[0.9375rem] text-ink outline-none transition placeholder:text-faint focus:border-accent focus:bg-surface"
        />

        {/* Fixed-height row so the dialog never jumps as the probe resolves. */}
        <div className="mt-1.5 flex h-5 items-center text-[0.75rem]" data-testid="probe-status">
          {probing ? (
            <span className="text-faint">Fetching title…</span>
          ) : title ? (
            <span className="truncate text-muted">
              <span className="text-faint">Title:</span> {title}
            </span>
          ) : looksLikeUrl(value) ? (
            <span className="text-faint">No title found — the link will be used.</span>
          ) : null}
        </div>

        <div className="mt-3 grid grid-cols-3 gap-2">
          <Picker
            label="Subject"
            testid="resource-subject"
            value={placement.subject_id ?? ''}
            options={subjects.map((s: Subject) => ({ id: s.id, name: s.name }))}
            onChange={(id) =>
              setPlacement({ subject_id: id, topic_id: null, subtopic_id: null })
            }
          />
          <Picker
            label="Topic"
            testid="resource-topic"
            value={placement.topic_id ?? ''}
            options={topics.map((t) => ({ id: t.id, name: t.name }))}
            disabled={!placement.subject_id}
            onChange={(id) =>
              setPlacement((p) => ({ ...p, topic_id: id, subtopic_id: null }))
            }
          />
          <Picker
            label="Subtopic"
            testid="resource-subtopic"
            value={placement.subtopic_id ?? ''}
            options={subtopics.map((st) => ({ id: st.id, name: st.name }))}
            disabled={!placement.topic_id}
            onChange={(id) => setPlacement((p) => ({ ...p, subtopic_id: id }))}
          />
        </div>

        {create.isError && (
          <p data-testid="resource-add-error" className="mt-3 text-[0.8125rem] text-stale">
            {(create.error as Error).message}
          </p>
        )}

        <div className="mt-4 flex items-center justify-between gap-2">
          <span className="text-[0.75rem] text-faint">Enter to save</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-md px-3 py-1.5 text-[0.8125rem] text-muted transition hover:bg-sunken hover:text-ink"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!value.trim() || create.isPending}
              data-testid="resource-add-submit"
              className="rounded-md bg-accent px-3.5 py-1.5 text-[0.8125rem] font-medium text-white transition hover:bg-accent-deep disabled:cursor-not-allowed disabled:opacity-40"
            >
              {create.isPending ? 'Adding…' : 'Add'}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}

function Picker({ label, testid, value, options, onChange, disabled }: {
  label: string
  testid: string
  value: number | ''
  options: Array<{ id: number; name: string }>
  onChange: (id: number | null) => void
  disabled?: boolean
}) {
  return (
    <label className="block min-w-0">
      <span className="mb-1 block text-[0.6875rem] font-medium text-ink-soft">{label}</span>
      <select
        value={value}
        disabled={disabled}
        data-testid={testid}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
        className="w-full truncate rounded-md border border-line bg-paper px-2 py-1.5 text-[0.8125rem] text-ink outline-none transition focus:border-accent focus:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
      >
        <option value="">—</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>{o.name}</option>
        ))}
      </select>
    </label>
  )
}
