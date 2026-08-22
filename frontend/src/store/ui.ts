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
  activeResourceId: number | null
  paletteOpen: boolean
  addDialogOpen: boolean
  resourceAddOpen: boolean

  toggleLeft: () => void
  toggleRight: () => void
  toggleSubject: (id: number) => void
  toggleTopic: (id: number) => void
  openSubtopic: (subtopicId: number, noteId: number) => void
  openResource: (resourceId: number) => void
  clearResource: () => void
  clearActive: () => void
  setPalette: (open: boolean) => void
  setAddDialog: (open: boolean) => void
  setResourceAdd: (open: boolean) => void
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
      activeResourceId: null,
      paletteOpen: false,
      addDialogOpen: false,
      resourceAddOpen: false,

      toggleLeft: () => set((s) => ({ leftCollapsed: !s.leftCollapsed })),
      toggleRight: () => set((s) => ({ rightCollapsed: !s.rightCollapsed })),
      toggleSubject: (id) => set((s) => ({ expandedSubjects: toggle(s.expandedSubjects, id) })),
      toggleTopic: (id) => set((s) => ({ expandedTopics: toggle(s.expandedTopics, id) })),
      openSubtopic: (subtopicId, noteId) =>
        set({
          activeSubtopicId: subtopicId,
          activeNoteId: noteId,
          // A subtopic note and a resource note are different surfaces; opening
          // one must close the other.
          activeResourceId: null,
          paletteOpen: false,
        }),
      openResource: (resourceId) =>
        set({
          activeResourceId: resourceId,
          activeSubtopicId: null,
          activeNoteId: null,
          paletteOpen: false,
        }),
      clearResource: () => set({ activeResourceId: null }),
      clearActive: () =>
        set({ activeSubtopicId: null, activeNoteId: null, activeResourceId: null }),
      setPalette: (open) => set({ paletteOpen: open }),
      setAddDialog: (open) => set({ addDialogOpen: open }),
      setResourceAdd: (open) => set({ resourceAddOpen: open }),
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
        activeResourceId: s.activeResourceId,
      }),
    },
  ),
)
