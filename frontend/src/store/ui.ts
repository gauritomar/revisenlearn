import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type UIState = {
  /** Spec §14 — sidebar collapse state is persisted. */
  leftCollapsed: boolean
  rightCollapsed: boolean
  expandedSubjects: number[]
  expandedTopics: number[]
  expandedSubtopics: number[]
  expandedLessons: number[]
  activeSubtopicId: number | null
  /** Consolidated addendum §3 — the lesson whose note is open. */
  activeLessonId: number | null
  activeNoteId: number | null
  activeResourceId: number | null
  activeDate: string | null
  paletteOpen: boolean
  addDialogOpen: boolean
  /** What ⌘K had typed when the quick-add was opened from it (§5). */
  addSeed: string
  resourceAddOpen: boolean
  /** §6 — which right-panel tab is showing, and whether a finished job is
   *  waiting behind another tab. A job must never steal the tab. */
  rightTab: RightTab
  pipelineBadge: boolean
  /** §6 — below ~900px the panels overlay, one at a time. */
  narrowPanel: 'left' | 'right' | null

  toggleLeft: () => void
  toggleRight: () => void
  toggleSubject: (id: number) => void
  toggleTopic: (id: number) => void
  toggleSubtopic: (id: number) => void
  toggleLesson: (id: number) => void
  openSubtopic: (subtopicId: number, noteId: number) => void
  openLesson: (lessonId: number, noteId: number) => void
  openResource: (resourceId: number) => void
  openDate: (date: string) => void
  clearResource: () => void
  clearActive: () => void
  setPalette: (open: boolean) => void
  setAddDialog: (open: boolean) => void
  openAddWith: (name: string) => void
  setResourceAdd: (open: boolean) => void
  setRightTab: (tab: RightTab) => void
  setPipelineBadge: (on: boolean) => void
  setNarrowPanel: (panel: 'left' | 'right' | null) => void
}

export type RightTab = 'checklist' | 'pipeline' | 'resources'

const toggle = (list: number[], id: number) =>
  list.includes(id) ? list.filter((x) => x !== id) : [...list, id]

export const useUI = create<UIState>()(
  persist(
    (set) => ({
      leftCollapsed: false,
      rightCollapsed: false,
      expandedSubjects: [],
      expandedTopics: [],
      expandedSubtopics: [],
      expandedLessons: [],
      activeSubtopicId: null,
      activeLessonId: null,
      activeNoteId: null,
      activeResourceId: null,
      activeDate: null,
      paletteOpen: false,
      addDialogOpen: false,
      addSeed: '',
      resourceAddOpen: false,
      rightTab: 'checklist',
      pipelineBadge: false,
      narrowPanel: null,

      toggleLeft: () => set((s) => ({ leftCollapsed: !s.leftCollapsed })),
      toggleRight: () => set((s) => ({ rightCollapsed: !s.rightCollapsed })),
      toggleSubject: (id) => set((s) => ({ expandedSubjects: toggle(s.expandedSubjects, id) })),
      toggleTopic: (id) => set((s) => ({ expandedTopics: toggle(s.expandedTopics, id) })),
      toggleSubtopic: (id) => set((s) => ({ expandedSubtopics: toggle(s.expandedSubtopics, id) })),
      toggleLesson: (id) => set((s) => ({ expandedLessons: toggle(s.expandedLessons, id) })),
      openLesson: (lessonId, noteId) =>
        set({
          activeLessonId: lessonId,
          activeNoteId: noteId,
          activeSubtopicId: null,
          activeResourceId: null,
          activeDate: null,
          paletteOpen: false,
          narrowPanel: null,
        }),
      openSubtopic: (subtopicId, noteId) =>
        set({
          activeSubtopicId: subtopicId,
          activeLessonId: null,
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
          activeLessonId: null,
          activeNoteId: null,
          activeDate: null,
          paletteOpen: false,
        }),
      openDate: (date) =>
        set({
          activeDate: date,
          activeNoteId: null,
          activeLessonId: null,
          activeSubtopicId: null,
          activeResourceId: null,
        }),
      clearResource: () => set({ activeResourceId: null }),
      clearActive: () =>
        set({
          activeSubtopicId: null,
          activeLessonId: null,
          activeNoteId: null,
          activeResourceId: null,
          activeDate: null,
        }),
      setPalette: (open) => set({ paletteOpen: open }),
      setAddDialog: (open) => set({ addDialogOpen: open, addSeed: '' }),
      openAddWith: (name) => set({ addDialogOpen: true, addSeed: name, paletteOpen: false }),
      setResourceAdd: (open) => set({ resourceAddOpen: open }),
      // §6 — switching tab by hand clears the badge; a finished job sets it
      // but never moves the user off what they were reading.
      setRightTab: (tab) =>
        set(tab === 'pipeline'
          ? { rightTab: tab, pipelineBadge: false }
          : { rightTab: tab }),
      setPipelineBadge: (on) => set({ pipelineBadge: on }),
      setNarrowPanel: (panel) => set({ narrowPanel: panel }),
    }),
    {
      name: 'rnl-ui',
      // Transient flags are not worth persisting across launches.
      partialize: (s) => ({
        leftCollapsed: s.leftCollapsed,
        rightCollapsed: s.rightCollapsed,
        expandedSubjects: s.expandedSubjects,
        expandedTopics: s.expandedTopics,
        expandedSubtopics: s.expandedSubtopics,
        expandedLessons: s.expandedLessons,
        activeSubtopicId: s.activeSubtopicId,
        activeLessonId: s.activeLessonId,
        activeNoteId: s.activeNoteId,
        rightTab: s.rightTab,
        activeResourceId: s.activeResourceId,
        activeDate: s.activeDate,
      }),
    },
  ),
)
