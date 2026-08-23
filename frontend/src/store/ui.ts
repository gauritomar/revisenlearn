import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { TreeKind } from '../lib/api'

type UIState = {
  /** Spec §14 — sidebar collapse state is persisted. */
  leftCollapsed: boolean
  rightCollapsed: boolean
  expandedSubjects: number[]
  expandedTopics: number[]
  expandedSubtopics: number[]
  expandedLessons: number[]
  /** Roadmap rows the user folded away, keyed "kind-id". Collapsed rather
   *  than expanded, so a new subject starts open. */
  collapsedRows: string[]
  activeSubtopicId: number | null
  /** Consolidated addendum §3 — the lesson whose note is open. */
  activeLessonId: number | null
  /** The open page: every level of the hierarchy is one. */
  activePage: { kind: TreeKind; id: number } | null
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
  /** A practice session started from somewhere other than the Practice
   *  screen — "revise what you studied on Tuesday" makes the session, and
   *  Practice runs it instead of showing its picker. */
  pendingPracticeSession: number | null

  toggleLeft: () => void
  toggleRight: () => void
  toggleSubject: (id: number) => void
  toggleTopic: (id: number) => void
  toggleSubtopic: (id: number) => void
  toggleLesson: (id: number) => void
  toggleRow: (key: string) => void
  openSubtopic: (subtopicId: number, noteId: number) => void
  openLesson: (lessonId: number, noteId: number) => void
  openPage: (kind: TreeKind, id: number) => void
  /** The page screen reports the note it loaded, so the right panel can
   *  follow it. */
  setActiveNote: (noteId: number) => void
  /** Open one specific note, rather than a page's own note. A page shows the
   *  page's note; an extra note under the same subtopic, or a search hit, is
   *  a note in its own right and opens as itself. */
  openNote: (noteId: number) => void
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
  setPendingPractice: (sessionId: number | null) => void
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
      collapsedRows: [],
      activeSubtopicId: null,
      activeLessonId: null,
      activePage: null,
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
      pendingPracticeSession: null,

      toggleLeft: () => set((s) => ({ leftCollapsed: !s.leftCollapsed })),
      toggleRight: () => set((s) => ({ rightCollapsed: !s.rightCollapsed })),
      toggleSubject: (id) => set((s) => ({ expandedSubjects: toggle(s.expandedSubjects, id) })),
      toggleTopic: (id) => set((s) => ({ expandedTopics: toggle(s.expandedTopics, id) })),
      toggleSubtopic: (id) => set((s) => ({ expandedSubtopics: toggle(s.expandedSubtopics, id) })),
      toggleLesson: (id) => set((s) => ({ expandedLessons: toggle(s.expandedLessons, id) })),
      toggleRow: (key) =>
        set((s) => ({
          collapsedRows: s.collapsedRows.includes(key)
            ? s.collapsedRows.filter((k) => k !== key)
            : [...s.collapsedRows, key],
        })),
      openLesson: (lessonId, noteId) =>
        set({
          activeLessonId: lessonId,
          activePage: { kind: 'lesson', id: lessonId },
          activeNoteId: noteId,
          activeSubtopicId: null,
          activeResourceId: null,
          activeDate: null,
          paletteOpen: false,
          narrowPanel: null,
        }),
      // Opening a page clears the note: the page screen fetches its own, so
      // the editor never shows the last page's text under a new title.
      openPage: (kind, id) =>
        set({
          activePage: { kind, id },
          activeLessonId: kind === 'lesson' ? id : null,
          activeSubtopicId: kind === 'subtopic' ? id : null,
          activeNoteId: null,
          activeResourceId: null,
          activeDate: null,
          paletteOpen: false,
          narrowPanel: null,
        }),
      openSubtopic: (subtopicId, noteId) =>
        set({
          activeSubtopicId: subtopicId,
          activeLessonId: null,
          activePage: { kind: 'subtopic', id: subtopicId },
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
          activePage: null,
          activeNoteId: null,
          activeDate: null,
          paletteOpen: false,
        }),
      openDate: (date) =>
        set({
          activeDate: date,
          activeNoteId: null,
          activeLessonId: null,
          activePage: null,
          activeSubtopicId: null,
          activeResourceId: null,
        }),
      clearResource: () => set({ activeResourceId: null }),
      clearActive: () =>
        set({
          activeSubtopicId: null,
          activeLessonId: null,
          activePage: null,
          activeNoteId: null,
          activeResourceId: null,
          activeDate: null,
        }),
      setActiveNote: (noteId) => set({ activeNoteId: noteId }),
      openNote: (noteId) =>
        set({
          activeNoteId: noteId,
          activePage: null,
          activeResourceId: null,
          activeDate: null,
          paletteOpen: false,
          narrowPanel: null,
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
      setPendingPractice: (sessionId) => set({ pendingPracticeSession: sessionId }),
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
        collapsedRows: s.collapsedRows,
        activeSubtopicId: s.activeSubtopicId,
        activeLessonId: s.activeLessonId,
        activePage: s.activePage,
        activeNoteId: s.activeNoteId,
        rightTab: s.rightTab,
        activeResourceId: s.activeResourceId,
        activeDate: s.activeDate,
      }),
    },
  ),
)
