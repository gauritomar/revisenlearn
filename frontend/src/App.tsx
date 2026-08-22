import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api, type AppMeta } from './lib/api'
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
import { Roadmap, Todos } from './components/Roadmap'
import { Graph } from './components/Graph'

/** Spec §14.1 [LOCKED] — both sidebars auto-collapse below 900px. */
const COLLAPSE_BELOW = 900

export function App() {
  const { data: meta } = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const [view, setView] = useState('Dashboard')

  const leftCollapsed = useUI((s) => s.leftCollapsed)
  const rightCollapsed = useUI((s) => s.rightCollapsed)
  const activeNoteId = useUI((s) => s.activeNoteId)
  const activeResourceId = useUI((s) => s.activeResourceId)
  const activeDate = useUI((s) => s.activeDate)
  const setPalette = useUI((s) => s.setPalette)
  const setAddDialog = useUI((s) => s.setAddDialog)
  const setResourceAdd = useUI((s) => s.setResourceAdd)
  const clearActive = useUI((s) => s.clearActive)

  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < COLLAPSE_BELOW,
  )

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
      if (e.key === 'Escape') {
        setPalette(false)
        setAddDialog(false)
        setResourceAdd(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setPalette, setAddDialog, setResourceAdd])

  // Below 900px the sidebars overlay the content rather than squeezing it, so
  // the editor stays the dominant element and the page never scrolls sideways.
  const showLeft = !leftCollapsed && !narrow
  const showRight = !rightCollapsed && !narrow

  // Choosing a tab closes whatever note or resource is open — otherwise the
  // open surface keeps winning and the tab appears to do nothing.
  const goToView = (next: string) => {
    clearActive()
    setView(next)
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header meta={meta} view={view} onView={goToView} />

      <div className="flex min-h-0 flex-1">
        {showLeft && <LeftSidebar />}

        <main className="min-w-0 flex-1 overflow-y-auto" data-testid="main-content">
          <MainContent
            view={view}
            onView={goToView}
            activeNoteId={activeNoteId}
            activeResourceId={activeResourceId}
            activeDate={activeDate}
            meta={meta}
          />
        </main>

        {showRight && <RightSidebar meta={meta} />}
      </div>

      {narrow && !leftCollapsed && (
        <div className="fixed inset-y-0 left-0 top-14 z-40 shadow-xl">
          <LeftSidebar />
        </div>
      )}

      <CommandPalette />
      <AddDialog />
      <ResourceQuickAdd />
    </div>
  )
}

function MainContent({ view, onView, activeNoteId, activeResourceId, activeDate, meta }: {
  view: string
  onView: (v: string) => void
  activeNoteId: number | null
  activeResourceId: number | null
  activeDate: string | null
  meta: AppMeta | undefined
}) {
  // An open surface wins over the current tab — the user clicked into it.
  if (activeResourceId !== null) return <ResourceSplitView resourceId={activeResourceId} />
  if (activeNoteId !== null) return <NoteEditor noteId={activeNoteId} />
  if (activeDate !== null) return <DayView date={activeDate} />
  if (view === 'Settings') return <Settings meta={meta} />
  if (view === 'Runs') return <Jobs />
  if (view === 'Practice') return <Practice />
  if (view === 'Revision') return <Revision />
  if (view === 'Roadmap') return <Roadmap />
  if (view === 'Todos') return <Todos />
  if (view === 'Graph') return <Graph />
  if (view === 'Resources') return <ResourceList />
  if (view === 'Notes') return <NotesEmpty />
  return <Dashboard onView={onView} />
}

function NotesEmpty() {
  const setAddDialog = useUI((s) => s.setAddDialog)
  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6" data-testid="notes-empty">
      <h2 className="text-xl font-semibold tracking-tight text-ink">Notes</h2>
      <p className="mt-1 text-[0.875rem] leading-relaxed text-muted">
        Pick a subtopic in the sidebar to open today&rsquo;s note, or open a
        resource to write against it.
      </p>
      <button
        type="button"
        onClick={() => setAddDialog(true)}
        className="mt-4 rounded-md border border-line bg-surface px-3 py-1.5 text-[0.8125rem] text-ink transition hover:border-accent hover:text-accent-deep"
      >
        Add a subject
      </button>
    </div>
  )
}
