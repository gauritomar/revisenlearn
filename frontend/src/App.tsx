import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api, type AppMeta, type TreeKind } from './lib/api'
import { useUI } from './store/ui'
import { Header } from './components/Header'
import { LeftSidebar } from './components/LeftSidebar'
import { RightSidebar } from './components/RightSidebar'
import { Dashboard } from './components/Dashboard'
import { NoteEditor } from './components/NoteEditor'
import { CommandPalette } from './components/CommandPalette'
import { AddDialog } from './components/AddDialog'
import { ResourceQuickAdd } from './components/ResourceQuickAdd'
import { ResourceList } from './components/ResourceList'
import { ResourceSplitView } from './components/ResourceSplitView'
import { DayView } from './components/Calendar'
import { Settings } from './components/Settings'
import { Jobs } from './components/Jobs'
import { Practice } from './components/Practice'
import { Revision } from './components/Revision'
import { PageScreen } from './components/PageScreen'
import { Roadmap, Todos } from './components/Roadmap'
import { Graph } from './components/Graph'
import { ShortcutOverlay, Usage } from './components/Usage'

/** Is the event coming from somewhere the user is writing?
 *
 *  Written as a named function on purpose: the inline form
 *  `!(e.target as HTMLElement)?.isContentEditable` parses as
 *  `(!e.target)?.isContentEditable`, which is not what it looks like.
 */
function isTyping(target: EventTarget | null): boolean {
  if (target instanceof HTMLInputElement) return true
  if (target instanceof HTMLTextAreaElement) return true
  if (target instanceof HTMLElement && target.isContentEditable) return true
  return false
}

/** Spec §14.1 [LOCKED] — both sidebars auto-collapse below 900px. */
const COLLAPSE_BELOW = 900

export function App() {
  const { data: meta } = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  // The Roadmap is the way into notes, so the app opens there.
  const [view, setView] = useState('Roadmap')

  const leftCollapsed = useUI((s) => s.leftCollapsed)
  const rightCollapsed = useUI((s) => s.rightCollapsed)
  const narrowPanel = useUI((s) => s.narrowPanel)
  const setNarrowPanel = useUI((s) => s.setNarrowPanel)
  const activePage = useUI((s) => s.activePage)
  const activeNoteId = useUI((s) => s.activeNoteId)
  const activeResourceId = useUI((s) => s.activeResourceId)
  const activeDate = useUI((s) => s.activeDate)
  const setPalette = useUI((s) => s.setPalette)
  const setAddDialog = useUI((s) => s.setAddDialog)
  const setResourceAdd = useUI((s) => s.setResourceAdd)
  const clearActive = useUI((s) => s.clearActive)

  const [shortcutsOpen, setShortcutsOpen] = useState(false)

  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < COLLAPSE_BELOW,
  )

  usePageRoute(activePage)

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${COLLAPSE_BELOW - 1}px)`)
    const onChange = (e: MediaQueryListEvent | MediaQueryList) => setNarrow(e.matches)
    onChange(mq)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  // Global shortcuts (spec §14.4). Cmd+S is owned by the editor.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPalette(true)
      }
      // §14.4 — a `?` overlay lists the shortcuts. A `?` typed into a note,
      // a search box or an answer is a question mark, not a shortcut.
      if (e.key === '?' && !isTyping(e.target)) {
        e.preventDefault()
        setShortcutsOpen(true)
      }
      if (e.key === 'Escape') {
        setPalette(false)
        setAddDialog(false)
        setResourceAdd(false)
        setShortcutsOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setPalette, setAddDialog, setResourceAdd])

  // Below 900px the sidebars overlay the content rather than squeezing it, so
  // the editor stays the dominant element and the page never scrolls sideways.
  // Consolidated addendum §6: overlay-style, and only one open at a time.
  const showLeft = !leftCollapsed && !narrow
  // The right panel is about the open note. Screens that are not a note —
  // the graph console, which has its own inspector — should not carry it.
  const showRight = !rightCollapsed && !narrow && view !== 'Graph'

  // Choosing a tab closes whatever note or resource is open — otherwise the
  // open surface keeps winning and the tab appears to do nothing.
  const goToView = (next: string) => {
    clearActive()
    setNarrowPanel(null)
    setView(next)
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header meta={meta} view={view} onView={goToView} narrow={narrow} />

      <div className="flex min-h-0 flex-1">
        {showLeft && <LeftSidebar />}

        <main className="min-w-0 flex-1 overflow-y-auto" data-testid="main-content">
          <MainContent
            view={view}
            onView={goToView}
            activePage={activePage}
            activeNoteId={activeNoteId}
            activeResourceId={activeResourceId}
            activeDate={activeDate}
            meta={meta}
          />
        </main>

        {showRight && <RightSidebar meta={meta} />}
      </div>

      {narrow && narrowPanel !== null && (
        <>
          <div
            className="fixed inset-0 top-14 z-30 bg-ink/10"
            onMouseDown={() => setNarrowPanel(null)}
            role="presentation"
          />
          <div
            data-testid={`overlay-${narrowPanel}`}
            className={[
              'fixed inset-y-0 top-14 z-40 shadow-xl',
              narrowPanel === 'left' ? 'left-0' : 'right-0',
            ].join(' ')}
          >
            {narrowPanel === 'left' ? <LeftSidebar /> : <RightSidebar meta={meta} />}
          </div>
        </>
      )}

      <CommandPalette />
      <AddDialog />
      <ResourceQuickAdd />
      {shortcutsOpen && <ShortcutOverlay onClose={() => setShortcutsOpen(false)} />}
    </div>
  )
}

function MainContent({ view, onView, activePage, activeNoteId, activeResourceId,
                      activeDate, meta }: {
  view: string
  onView: (v: string) => void
  activePage: { kind: TreeKind; id: number } | null
  activeNoteId: number | null
  activeResourceId: number | null
  activeDate: string | null
  meta: AppMeta | undefined
}) {
  // An open surface wins over the current tab — the user clicked into it.
  if (activeResourceId !== null) return <ResourceSplitView resourceId={activeResourceId} />
  if (activePage !== null) return <PageScreen kind={activePage.kind} id={activePage.id} />
  if (activeNoteId !== null) return <NoteEditor noteId={activeNoteId} />
  if (activeDate !== null) return <DayView date={activeDate} />
  if (view === 'Settings') return <Settings meta={meta} />
  if (view === 'Runs') return <Jobs />
  if (view === 'Practice') return <Practice />
  if (view === 'Revision') return <Revision />
  if (view === 'Roadmap') return <Roadmap />
  if (view === 'Todos') return <Todos />
  if (view === 'Graph') return <Graph />
  if (view === 'Usage') return <Usage />
  if (view === 'Resources') return <ResourceList />
  return <Dashboard onView={onView} />
}


/** Real page navigation, in the hash.
 *
 *  Consolidated addendum §3 asked for "real page navigation (e.g. route
 *  `/lessons/{id}`), not an inline pane swap"; now that every level of the
 *  hierarchy is a page, the route covers all four. One window, no router, so
 *  the route lives in `location.hash`: opening a page pushes
 *  `#/pages/subtopic/3`, Back works, and a reload lands where you were.
 */
const PAGE_KINDS: TreeKind[] = ['subject', 'topic', 'subtopic', 'lesson']

function usePageRoute(activePage: { kind: TreeKind; id: number } | null) {
  const openPage = useUI((s) => s.openPage)
  const clearActive = useUI((s) => s.clearActive)

  // State → URL.
  useEffect(() => {
    const wanted = activePage === null
      ? '' : `#/pages/${activePage.kind}/${activePage.id}`
    if (window.location.hash === wanted) return
    if (wanted) window.history.pushState(null, '', wanted)
    else window.history.pushState(null, '', window.location.pathname)
  }, [activePage?.kind, activePage?.id])

  // URL → state, for Back, Forward and a reload.
  useEffect(() => {
    const apply = () => {
      const match = /^#\/pages\/([a-z]+)\/(\d+)$/.exec(window.location.hash)
      const state = useUI.getState()
      if (match && (PAGE_KINDS as string[]).includes(match[1])) {
        const kind = match[1] as TreeKind
        const id = Number(match[2])
        if (state.activePage?.kind !== kind || state.activePage?.id !== id) {
          openPage(kind, id)
        }
      } else if (state.activePage !== null) {
        clearActive()
      }
    }
    apply()
    window.addEventListener('popstate', apply)
    window.addEventListener('hashchange', apply)
    return () => {
      window.removeEventListener('popstate', apply)
      window.removeEventListener('hashchange', apply)
    }
    // Runs once: the listeners read live state themselves.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}
