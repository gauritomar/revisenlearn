import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { api, type PageChild, type TreeKind } from '../lib/api'
import { useRefreshEverything } from '../lib/refresh'
import { useUI } from '../store/ui'
import { NoteEditor } from './NoteEditor'

/** A page — which is every level of the hierarchy.
 *
 *  "A Notion type interface where everything is a page and pages under pages;
 *  when I open a page I should be able to see all the pages under it too."
 *
 *  So: the trail above, the page's own note, and the pages inside it. A
 *  Subject and a Lesson are the same screen; only what they can contain
 *  differs (spec §3 [LOCKED] still fixes the levels — Subject, Topic,
 *  Subtopic, then Lessons).
 */
const CHILD_LABEL: Record<TreeKind, string> = {
  subject: 'Topic',
  topic: 'Subtopic',
  subtopic: 'Lesson',
  lesson: '',
}

export function PageScreen({ kind, id }: { kind: TreeKind; id: number }) {
  const openPage = useUI((s) => s.openPage)
  const setActiveNote = useUI((s) => s.setActiveNote)
  const refresh = useRefreshEverything()
  const [adding, setAdding] = useState(false)

  const { data: page, isLoading } = useQuery({
    queryKey: ['page', kind, id],
    queryFn: () => api.page(kind, id),
  })

  // The right panel (checklist, concepts, links) follows the open note. A
  // page fetches its own note, so it has to say which one that is — without
  // this the panel goes blank the moment you open a page.
  useEffect(() => {
    if (page?.note_id) setActiveNote(page.note_id)
  }, [page?.note_id, setActiveNote])

  const addChild = useMutation({
    mutationFn: async (name: string) => {
      if (kind === 'subject') return api.createTopic(id, name)
      if (kind === 'topic') return api.createSubtopic(id, name)
      // A subtopic's children are lessons, which need their topic too.
      const topicId = page?.breadcrumb.find((b) => b.kind === 'topic')?.id
      return api.createLesson({ topic_id: topicId, subtopic_id: id, name })
    },
    // Stays open, so several pages can be added in one burst (addendum §7).
    onSuccess: refresh,
  })

  if (isLoading || !page) {
    return <div className="p-6 text-[0.8125rem] text-faint">Opening…</div>
  }

  const childLabel = CHILD_LABEL[kind]

  return (
    <div
      data-testid="page-screen"
      data-page-kind={kind}
      className="mx-auto flex h-full w-full max-w-3xl flex-col px-4 py-5 sm:px-6"
    >
      {page.breadcrumb.length > 0 && (
        <nav data-testid="page-breadcrumb" className="mb-1 flex flex-wrap items-center gap-1 text-[0.75rem]">
          {page.breadcrumb.map((crumb, i) => (
            <span key={`${crumb.kind}-${crumb.id}`} className="flex items-center gap-1">
              {i > 0 && <span className="text-faint" aria-hidden="true">›</span>}
              <button
                type="button"
                onClick={() => openPage(crumb.kind, crumb.id)}
                data-testid={`crumb-${crumb.kind}-${crumb.id}`}
                className="rounded px-1 py-0.5 text-muted transition hover:bg-sunken hover:text-ink"
              >
                {crumb.name}
              </button>
            </span>
          ))}
        </nav>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* The note is the page. */}
        <NoteEditor noteId={page.note_id} titleOverride={page.name} />

        <PageLink kind={kind} id={id} url={page.url} onSaved={refresh} />

        {childLabel && (
          <section data-testid="page-children" className="mt-8 border-t border-line-soft pt-4">
            <h3 className="mb-2 text-[0.6875rem] font-semibold uppercase tracking-[0.09em] text-muted">
              Inside {page.name}
            </h3>

            {page.children.length === 0 && !adding && (
              <p className="mb-2 text-[0.8125rem] text-faint">
                Nothing inside yet.
              </p>
            )}

            <ul className="space-y-0.5">
              {page.children.map((child) => (
                <ChildRow key={`${child.kind}-${child.id}`} child={child}
                          onOpen={() => openPage(child.kind, child.id)} />
              ))}
            </ul>

            {adding ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  const input = e.currentTarget.elements.namedItem('name') as HTMLInputElement
                  const name = input.value.trim()
                  if (name) addChild.mutate(name)
                  input.value = ''
                }}
                className="mt-1"
              >
                <input
                  name="name"
                  autoFocus
                  data-testid="page-add-child-input"
                  placeholder={`${childLabel} name — Enter to add, Esc to cancel`}
                  onKeyDown={(e) => { if (e.key === 'Escape') setAdding(false) }}
                  onBlur={(e) => { if (!e.currentTarget.value.trim()) setAdding(false) }}
                  className="w-full rounded-md border border-accent bg-surface px-2 py-1.5 text-[0.8125rem] text-ink outline-none"
                />
              </form>
            ) : (
              <button
                type="button"
                onClick={() => setAdding(true)}
                data-testid="page-add-child"
                className="mt-1 flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[0.8125rem] text-faint transition hover:bg-sunken hover:text-ink"
              >
                <span aria-hidden="true">+</span> New {childLabel.toLowerCase()}
              </button>
            )}
          </section>
        )}
      </div>
    </div>
  )
}

function ChildRow({ child, onOpen }: { child: PageChild; onOpen: () => void }) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        data-testid={`page-child-${child.kind}-${child.id}`}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition hover:bg-sunken"
      >
        <PageIcon />
        <span className="min-w-0 flex-1 truncate text-[0.8125rem] text-ink">
          {child.name}
        </span>
        <span className="shrink-0 text-[0.6875rem] tabular-nums text-faint">
          {child.block_count > 0 && `${child.block_count} block${child.block_count === 1 ? '' : 's'}`}
          {child.block_count > 0 && child.child_count > 0 && ' · '}
          {child.child_count > 0 && `${child.child_count} inside`}
        </span>
      </button>
    </li>
  )
}

function PageIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true"
         className="shrink-0 text-faint">
      <path d="M3 1.5h4l2 2v7H3z" stroke="currentColor" strokeWidth="1.1"
            strokeLinejoin="round" />
      <path d="M7 1.5v2h2" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" />
    </svg>
  )
}


/** The source a page came from — an article, a lecture, a problem set.
 *
 *  "I should be able to embed links in topic/lesson names … and that link
 *  should be displayed when its page is open." It sits under the title rather
 *  than inside the note, because it belongs to the page, not to the writing:
 *  it should not be sent to the model as content, and it should still be
 *  there when the note is rewritten.
 */
function PageLink({ kind, id, url, onSaved }: {
  kind: TreeKind
  id: number
  url: string | null
  onSaved: () => void | Promise<void>
}) {
  const [editing, setEditing] = useState(false)

  const save = useMutation({
    mutationFn: (value: string | null) => api.setPageUrl(kind, id, value),
    onSuccess: async () => { setEditing(false); await onSaved() },
  })

  if (editing) {
    return (
      <form
        className="mt-2"
        onSubmit={(e) => {
          e.preventDefault()
          const input = e.currentTarget.elements.namedItem('url') as HTMLInputElement
          save.mutate(input.value.trim() || null)
        }}
      >
        <input
          name="url"
          autoFocus
          defaultValue={url ?? ''}
          data-testid="page-link-input"
          placeholder="https://…  (Enter to save, Esc to cancel, empty to remove)"
          onKeyDown={(e) => { if (e.key === 'Escape') setEditing(false) }}
          className="w-full rounded-md border border-accent bg-surface px-2 py-1 text-[0.75rem] text-ink outline-none"
        />
      </form>
    )
  }

  if (!url) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        data-testid="page-link-add"
        className="mt-2 text-[0.75rem] text-faint transition hover:text-accent-deep"
      >
        + Link an article, lecture or problem
      </button>
    )
  }

  return (
    <p className="mt-2 flex items-center gap-2">
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        data-testid="page-link"
        className="min-w-0 flex-1 truncate text-[0.75rem] text-accent-deep underline decoration-line underline-offset-2 hover:decoration-accent"
      >
        {url}
      </a>
      <button
        type="button"
        onClick={() => setEditing(true)}
        data-testid="page-link-edit"
        className="shrink-0 text-[0.6875rem] text-faint transition hover:text-ink"
      >
        change
      </button>
    </p>
  )
}
