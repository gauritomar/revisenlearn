import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, type SearchHit } from '../lib/api'
import { useUI } from '../store/ui'

/** Spec §14.4 — Cmd+K global search, Esc closes. Phase 1 searches note blocks
 *  and concepts over FTS5; the semantic half arrives with embeddings in
 *  Phase 4. */
export function CommandPalette() {
  const open = useUI((s) => s.paletteOpen)
  const setPalette = useUI((s) => s.setPalette)
  const openNote = useUI((s) => s.openNote)
  const openAddWith = useUI((s) => s.openAddWith)
  const qc = useQueryClient()

  const [q, setQ] = useState('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) { setQ(''); setHits([]); return }
    // Autofocus on open so the user types straight into it.
    const id = window.setTimeout(() => inputRef.current?.focus(), 0)
    return () => window.clearTimeout(id)
  }, [open])

  // Debounced query. 120ms keeps it responsive without a request per keystroke.
  useEffect(() => {
    if (!open) return
    if (!q.trim()) { setHits([]); return }
    let cancelled = false
    setBusy(true)
    const id = window.setTimeout(async () => {
      try {
        const res = await api.search(q)
        if (!cancelled) setHits(res.hits)
      } catch {
        if (!cancelled) setHits([])
      } finally {
        if (!cancelled) setBusy(false)
      }
    }, 120)
    return () => { cancelled = true; window.clearTimeout(id) }
  }, [q, open])

  if (!open) return null

  async function pick(hit: SearchHit) {
    if (hit.kind === 'note_block' && hit.note_id !== null) {
      const note = await api.note(hit.note_id)
      qc.setQueryData(['note', note.id], note)
      openNote(note.id)
    }
    setPalette(false)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-ink/15 px-4 pt-[12vh] backdrop-blur-[2px]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) setPalette(false) }}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search"
        data-testid="command-palette"
        className="w-full max-w-xl overflow-hidden rounded-xl border border-line bg-surface shadow-xl"
      >
        <div className="flex items-center gap-2.5 border-b border-line-soft px-3.5">
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" className="shrink-0 text-faint" aria-hidden="true">
            <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4" />
            <path d="M10.5 10.5 14 14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search notes and concepts"
            data-testid="palette-input"
            aria-label="Search notes and concepts"
            className="h-12 w-full bg-transparent text-[0.9375rem] text-ink outline-none placeholder:text-faint"
          />
          <kbd className="shrink-0 rounded border border-line px-1.5 py-0.5 text-[0.6875rem] text-faint">
            Esc
          </kbd>
        </div>

        <div className="max-h-[52vh] overflow-y-auto p-1.5" data-testid="palette-results">
          {q.trim() === '' ? (
            <p className="px-2.5 py-6 text-center text-[0.8125rem] text-faint">
              Type to search your notes.
            </p>
          ) : hits.length === 0 ? (
            <p data-testid="palette-no-results" className="px-2.5 py-6 text-center text-[0.8125rem] text-faint">
              {busy ? 'Searching…' : `No matches for “${q}”.`}
            </p>
          ) : (
            <ul className="space-y-0.5">
              {hits.map((hit, i) => (
                <li key={`${hit.kind}-${hit.note_block_id ?? hit.concept_id}-${i}`}>
                  <button
                    type="button"
                    onClick={() => void pick(hit)}
                    data-testid="palette-result"
                    className="w-full rounded-lg px-2.5 py-2 text-left transition hover:bg-sunken"
                  >
                    <div className="flex items-baseline gap-2">
                      <span className="truncate text-[0.8125rem] font-medium text-ink">
                        {hit.title}
                      </span>
                      <span className="ml-auto shrink-0 text-[0.6875rem] uppercase tracking-wide text-faint">
                        {hit.kind === 'note_block' ? 'note' : 'concept'}
                      </span>
                    </div>
                    {/* FTS5 returns <mark> around the matched terms. The value
                        is snippet() output over the user's own local text. */}
                    <p
                      className="mt-0.5 line-clamp-2 text-[0.8125rem] leading-snug text-muted"
                      dangerouslySetInnerHTML={{ __html: hit.snippet }}
                    />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* §5 — the quick-add is "reachable via ⌘K", carrying whatever was
            already typed as the new item's name. */}
        <div className="border-t border-line-soft p-1.5">
          <button
            type="button"
            onClick={() => openAddWith(q.trim())}
            data-testid="palette-add"
            className="flex w-full items-baseline gap-2 rounded-lg px-2.5 py-2 text-left transition hover:bg-sunken"
          >
            <span className="text-[0.8125rem] text-ink">
              {q.trim() ? <>Add &ldquo;{q.trim()}&rdquo; to the tree</> : 'Add to the tree'}
            </span>
            <span className="ml-auto shrink-0 text-[0.6875rem] uppercase tracking-wide text-faint">
              new
            </span>
          </button>
        </div>
      </div>
    </div>
  )
}
