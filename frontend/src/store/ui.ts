import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type UIState = {
  /** Spec §14 — sidebar collapse state is persisted. */
  leftCollapsed: boolean
  rightCollapsed: boolean
  expandedSubjects: number[]
  expandedTopics: number[]
  activeSubtopicId: number | null
  activeNoteId: number | null
  paletteOpen: boolean
  addDialogOpen: boolean

  toggleLeft: () => void
  toggleRight: () => void
  toggleSubject: (id: number) => void
  toggleTopic: (id: number) => void
  openSubtopic: (subtopicId: number, noteId: number) => void
  clearActive: () => void
  setPalette: (open: boolean) => void
  setAddDialog: (open: boolean) => void
}

const toggle = (list: number[], id: number) =>
  list.includes(id) ? list.filter((x) => x !== id) : [...list, id]

export const useUI = create<UIState>()(
  persist(
    (set) => ({
      leftCollapsed: false,
      rightCollapsed: false,
      expandedSubjects: [],
      expandedTopics: [],
      activeSubtopicId: null,
      activeNoteId: null,
      paletteOpen: false,
      addDialogOpen: false,

      toggleLeft: () => set((s) => ({ leftCollapsed: !s.leftCollapsed })),
      toggleRight: () => set((s) => ({ rightCollapsed: !s.rightCollapsed })),
      toggleSubject: (id) => set((s) => ({ expandedSubjects: toggle(s.expandedSubjects, id) })),
      toggleTopic: (id) => set((s) => ({ expandedTopics: toggle(s.expandedTopics, id) })),
      openSubtopic: (subtopicId, noteId) =>
        set({ activeSubtopicId: subtopicId, activeNoteId: noteId, paletteOpen: false }),
      clearActive: () => set({ activeSubtopicId: null, activeNoteId: null }),
      setPalette: (open) => set({ paletteOpen: open }),
      setAddDialog: (open) => set({ addDialogOpen: open }),
    }),
    {
      name: 'rnl-ui',
      // Transient flags are not worth persisting across launches.
      partialize: (s) => ({
        leftCollapsed: s.leftCollapsed,
        rightCollapsed: s.rightCollapsed,
        expandedSubjects: s.expandedSubjects,
        expandedTopics: s.expandedTopics,
        activeSubtopicId: s.activeSubtopicId,
        activeNoteId: s.activeNoteId,
      }),
    },
  ),
)
