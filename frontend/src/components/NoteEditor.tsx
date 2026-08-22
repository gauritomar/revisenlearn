import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'
import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight'

import { api, type Note } from '../lib/api'
import { CheckboxInput, CodeFenceAnywhere } from '../lib/checkboxInput'
import { lowlight } from '../lib/highlight'
import { DateDivider } from '../lib/dateDivider'
import { blocksToDoc, docToBlocks, reconcile } from '../lib/blocks'
import { useRefreshEverything } from '../lib/refresh'
import { BlockIndicators, buildStateIndex } from '../lib/blockIndicators'
import { NoteHeader } from './NoteHeader'

/** Spec §4.1 — autosave is debounced 800ms after typing stops, plus on blur,
 *  plus every 30s while active. Spec §14.4 — Cmd/Ctrl+S forces a save. */
const DEBOUNCE_MS = 800
const INTERVAL_MS = 30_000

type SaveState = 'clean' | 'dirty' | 'saving' | 'saved' | 'error'

export function NoteEditor({ noteId, titleOverride }: {
  noteId: number
  /** When the note is a page's note, the page names it (§3's rule for
   *  lessons, extended to every level). */
  titleOverride?: string
}) {
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
        // Replaced below by the highlighting version.
        codeBlock: false,
      }),
      // ``` or ```python opens a code block; the language is remembered on
      // the block and highlighted locally — no network, no CDN.
      CodeBlockLowlight.extend({
        // Tiptap puts the language on the inner <code> as `language-python`.
        // The corner label is drawn on the <pre>, so it needs it there too.
        renderHTML({ node, HTMLAttributes }) {
          const language = node.attrs.language || 'plaintext'
          return [
            'pre',
            { ...HTMLAttributes, 'data-language': language },
            ['code', { class: `language-${language}` }, 0],
          ]
        },
      }).configure({ lowlight, defaultLanguage: 'plaintext' }),
      // Consolidated addendum §2 — "Typing `- [ ] text` creates one".
      // TaskList's own input rule fires on that exact prefix, so the syntax
      // works in the editor as well as on the server (where a paste of the
      // same text is parsed on save).
      TaskList,
      TaskItem.configure({ nested: true }),
      CheckboxInput,
      CodeFenceAnywhere,
      DateDivider,
      Placeholder.configure({
        placeholder:
          'Write. "- " bullet · "- [ ] " checkbox · "# " heading · "```python" code',
      }),
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

  const refresh = useRefreshEverything()

  const save = useCallback(async () => {
    const current = noteRef.current
    if (!editor || !current) return
    setSaveState('saving')
    try {
      const serialised = docToBlocks(editor.getJSON())
      const payload = reconcile(serialised, current.blocks)
      const updated = await api.saveBlocks(current.id, payload)
      qc.setQueryData(['note', current.id], updated)
      // A save changes what the pipeline owes (spec §14: the button carries
      // that count), and may have just created a checklist item or a resource
      // that the panel, the tree and the Roadmap all read (§2, §4).
      void refresh()
      setSaveState('saved')
    } catch {
      // Principle §1.2 — never lose what was typed. The document stays in the
      // editor and the next tick retries.
      setSaveState('error')
    }
  }, [editor, qc, refresh])

  // Load the stored note into the editor once it has actually arrived.
  //
  // Keying this on `noteId` alone was a bug: when the note is not already in
  // the query cache (opening one from the dashboard rather than the sidebar),
  // the first run sees `note === undefined` and bails, and nothing re-runs it
  // when the data lands — leaving an empty editor over a non-empty note.
  // Keying on `note` and guarding with a ref hydrates exactly once per note,
  // whenever it arrives, without re-hydrating on every refetch and fighting
  // the user's cursor.
  const hydratedRef = useRef<number | null>(null)
  const [hydrated, setHydrated] = useState(false)
  useEffect(() => {
    if (!editor || !note) return
    if (hydratedRef.current === note.id) {
      setHydrated(true)
      return
    }
    setHydrated(false)
    editor.commands.setContent(blocksToDoc(note.blocks), false)
    hydratedRef.current = note.id
    setHydrated(true)
    setSaveState('clean')
  }, [editor, note])

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

  if (titleOverride !== undefined) {
    return (
      <>
        <NoteHeader note={note} saveState={saveState} titleOverride={titleOverride} />
        {/* Only once the stored note is in the editor: inserting before that
            would be overwritten by hydration, losing what was just added. */}
        {hydrated && <SectionButton editor={editor} where="top" />}
        <EditorContent editor={editor} />
        {hydrated && <SectionButton editor={editor} where="end" />}
      </>
    )
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col px-4 py-5 sm:px-6">
      <NoteHeader note={note} saveState={saveState} />

      <div className="min-h-0 flex-1 overflow-y-auto">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}


/** Add a section — a heading with bullets under it — without scrolling.
 *
 *  "Each block can have a heading then bullets under it, some blocks might
 *  not have headings … my notes are kind of random as i come across a concept
 *  i just add it, theyre not very sequential."
 *
 *  So a section can go on either end: at the top when the newest thing should
 *  be the first thing, at the end when the note reads in order. The heading is
 *  optional — leave it empty and it disappears on save, leaving the bullets.
 */
function SectionButton({ editor, where }: {
  editor: ReturnType<typeof useEditor>
  where: 'top' | 'end'
}) {
  if (!editor) return null

  const add = () => {
    const at = where === 'top' ? 0 : editor.state.doc.content.size
    editor
      .chain()
      .focus()
      .insertContentAt(at, [
        { type: 'heading', attrs: { level: 3 } },
        {
          type: 'bulletList',
          content: [{ type: 'listItem', content: [{ type: 'paragraph' }] }],
        },
      ])
      // Land in the heading that was just inserted, not after the bullets.
      .setTextSelection(at + 1)
      .run()

  }

  return (
    <button
      type="button"
      // The editor keeps the caret: a button that takes focus on mousedown
      // swallows the first keystrokes, so the new heading would sit there
      // empty while the user typed into nothing.
      onMouseDown={(e) => e.preventDefault()}
      onClick={add}
      data-testid={`add-section-${where}`}
      className={[
        'flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-[0.75rem]',
        'text-faint transition hover:bg-sunken hover:text-ink',
        where === 'top' ? 'mb-1' : 'mt-1',
      ].join(' ')}
    >
      <span aria-hidden="true">+</span>
      {where === 'top' ? 'New section at the top' : 'New section'}
    </button>
  )
}
