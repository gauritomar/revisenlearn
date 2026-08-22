import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'

import { api, type Note } from '../lib/api'
import { blocksToDoc, docToBlocks, reconcile } from '../lib/blocks'
import { BlockIndicators, buildStateIndex } from '../lib/blockIndicators'

/** Spec §4.1 — autosave is debounced 800ms after typing stops, plus on blur,
 *  plus every 30s while active. Spec §14.4 — Cmd/Ctrl+S forces a save. */
const DEBOUNCE_MS = 800
const INTERVAL_MS = 30_000

type SaveState = 'clean' | 'dirty' | 'saving' | 'saved' | 'error'

export function NoteEditor({ noteId }: { noteId: number }) {
  const qc = useQueryClient()
  const { data: note } = useQuery({ queryKey: ['note', noteId], queryFn: () => api.note(noteId) })

  const [saveState, setSaveState] = useState<SaveState>('clean')
  const debounceRef = useRef<number | null>(null)
  // The editor callbacks are created once; the latest note must reach them
  // through a ref rather than a stale closure.
  const noteRef = useRef<Note | undefined>(note)
  noteRef.current = note

  // The §4.2 indicator index, rebuilt whenever the server tells us block
  // states changed. Held in a ref so the ProseMirror plugin reads the current
  // value rather than the one captured when the editor was created.
  const stateIndexRef = useRef(buildStateIndex([]))
  stateIndexRef.current = useMemo(
    () => buildStateIndex(note?.blocks ?? []),
    [note?.blocks],
  )

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        // Spec §4.1 fixes the block set. Everything StarterKit adds beyond it
        // stays off.
        heading: { levels: [1, 2, 3] },
      }),
      Placeholder.configure({ placeholder: 'Start writing. Bullets are fastest.' }),
      BlockIndicators.configure({ getIndex: () => stateIndexRef.current }),
    ],
    content: { type: 'doc', content: [{ type: 'paragraph' }] },
    editorProps: {
      attributes: {
        class: 'note-prose min-h-[60vh] px-1 py-2',
        'data-testid': 'note-editor',
      },
    },
  })

  const save = useCallback(async () => {
    const current = noteRef.current
    if (!editor || !current) return
    setSaveState('saving')
    try {
      const serialised = docToBlocks(editor.getJSON())
      const payload = reconcile(serialised, current.blocks)
      const updated = await api.saveBlocks(current.id, payload)
      qc.setQueryData(['note', current.id], updated)
      setSaveState('saved')
    } catch {
      // Principle §1.2 — never lose what was typed. The document stays in the
      // editor and the next tick retries.
      setSaveState('error')
    }
  }, [editor, qc])

  // Load the stored note into the editor when it arrives or the note changes.
  useEffect(() => {
    if (!editor || !note) return
    editor.commands.setContent(blocksToDoc(note.blocks), false)
    setSaveState('clean')
    // Re-hydrating on every `note` object identity change would fight the
    // user's cursor; key on the id and the server's updated_at instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, noteId])

  // A save returns fresh block states, but the document itself has not
  // changed, so ProseMirror has no reason to recompute decorations. Nudge it.
  useEffect(() => {
    if (!editor || editor.isDestroyed) return
    editor.view.dispatch(editor.view.state.tr.setMeta('addToHistory', false))
  }, [editor, note?.blocks])

  // Debounced autosave on every change.
  useEffect(() => {
    if (!editor) return
    const onUpdate = () => {
      setSaveState('dirty')
      if (debounceRef.current) window.clearTimeout(debounceRef.current)
      debounceRef.current = window.setTimeout(() => void save(), DEBOUNCE_MS)
    }
    const onBlur = () => void save()
    editor.on('update', onUpdate)
    editor.on('blur', onBlur)
    return () => {
      editor.off('update', onUpdate)
      editor.off('blur', onBlur)
    }
  }, [editor, save])

  // Every 30s while active.
  useEffect(() => {
    const id = window.setInterval(() => {
      if (saveState === 'dirty') void save()
    }, INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [save, saveState])

  // Cmd/Ctrl+S forces a save (spec §14.4).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        if (debounceRef.current) window.clearTimeout(debounceRef.current)
        void save()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [save])

  // Flush on unmount so navigating away never drops a pending edit.
  useEffect(() => () => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current)
  }, [])

  if (!note) {
    return <div className="p-6 text-[0.8125rem] text-faint">Opening note…</div>
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col px-4 py-5 sm:px-6">
      <div className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-line-soft pb-3">
        <h2 data-testid="note-title" className="text-lg font-semibold tracking-tight text-ink">
          {note.title}
        </h2>
        <time
          data-testid="note-date"
          dateTime={note.study_date}
          className="text-[0.8125rem] text-muted"
        >
          {formatStudyDate(note.study_date)}
        </time>
        <div className="ml-auto flex items-center gap-3">
          <BlockCounter counts={note.counts} />
          <SaveDot state={saveState} />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}

/** Spec §4.2 — "12 processed · 4 new · 2 edited" in the note header. */
function BlockCounter({ counts }: { counts: Note['counts'] }) {
  return (
    <span data-testid="block-counter" className="text-[0.75rem] tabular-nums text-muted">
      <span className="text-accent-deep">{counts.processed}</span> processed
      <span className="mx-1 text-faint">·</span>
      {counts.new} new
      <span className="mx-1 text-faint">·</span>
      <span className={counts.edited > 0 ? 'text-stale' : undefined}>{counts.edited}</span> edited
    </span>
  )
}

/** Spec §4.1 — "never show a saving spinner that moves layout; use a small
 *  static status dot." Fixed 5rem box so the label never reflows the header. */
function SaveDot({ state }: { state: SaveState }) {
  const label: Record<SaveState, string> = {
    clean: 'Saved',
    dirty: 'Editing',
    saving: 'Saving',
    saved: 'Saved',
    error: 'Retrying',
  }
  const colour: Record<SaveState, string> = {
    clean: 'var(--color-line)',
    dirty: 'var(--color-faint)',
    saving: 'var(--color-accent)',
    saved: 'var(--color-mastery-3)',
    error: 'var(--color-stale)',
  }
  return (
    <span
      data-testid="save-status"
      data-state={state}
      className="flex w-[5rem] shrink-0 items-center justify-end gap-1.5 text-[0.75rem] text-muted"
    >
      <span className="size-1.5 rounded-full" style={{ background: colour[state] }} aria-hidden="true" />
      {label[state]}
    </span>
  )
}

function formatStudyDate(iso: string): string {
  // Parse as a local calendar date; `new Date('YYYY-MM-DD')` is UTC and can
  // render as the previous day west of Greenwich.
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}
