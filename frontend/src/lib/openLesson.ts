import { useQueryClient } from '@tanstack/react-query'

import { api } from './api'
import { useUI } from '../store/ui'

/** Consolidated addendum §3 — "Clicking a Lesson anywhere in the app opens
 *  this note directly."
 *
 *  Anywhere means the sidebar, the Roadmap, the Todos board and the command
 *  palette, so the behaviour lives in one place: ensure the lesson's single
 *  continuous note exists, prime the cache with it so the editor paints
 *  without a second round trip, then navigate.
 */
export function useOpenLesson() {
  const qc = useQueryClient()
  const openLesson = useUI((s) => s.openLesson)

  return async function open(lessonId: number) {
    const note = await api.ensureLessonNote(lessonId)
    qc.setQueryData(['note', note.id], note)
    openLesson(lessonId, note.id)
    return note
  }
}
