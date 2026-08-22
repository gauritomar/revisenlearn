import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from './lib/api'
import { useUI } from './store/ui'
import { Header } from './components/Header'
import { LeftSidebar } from './components/LeftSidebar'
import { RightSidebar } from './components/RightSidebar'
import { Dashboard } from './components/Dashboard'
import { NoteEditor } from './components/NoteEditor'
import { CommandPalette } from './components/CommandPalette'
import { AddDialog } from './components/AddDialog'

/** Spec §14.1 [LOCKED] — both sidebars auto-collapse below 900px. */
const COLLAPSE_BELOW = 900

export function App() {
  const { data: meta } = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const [view, setView] = useState('Dashboard')

  const leftCollapsed = useUI((s) => s.leftCollapsed)
  const rightCollapsed = useUI((s) => s.rightCollapsed)
  const activeNoteId = useUI((s) => s.activeNoteId)
  const setPalette = useUI((s) => s.setPalette)
  const setAddDialog = useUI((s) => s.setAddDialog)

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
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setPalette, setAddDialog])

  // Below 900px the sidebars overlay the content rather than squeezing it, so
  // the editor stays the dominant element and the page never scrolls sideways.
  const showLeft = !leftCollapsed && !narrow
  const showRight = !rightCollapsed && !narrow

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header meta={meta} view={view} onView={setView} />

      <div className="flex min-h-0 flex-1">
        {showLeft && <LeftSidebar />}

        <main className="min-w-0 flex-1 overflow-y-auto" data-testid="main-content">
          {activeNoteId !== null ? <NoteEditor noteId={activeNoteId} /> : <Dashboard />}
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
    </div>
  )
}
