import { useQueryClient } from '@tanstack/react-query'

/** One place that says "the world changed, refetch it".
 *
 *  Every add, rename, move and delete touches more than one screen: the
 *  sidebar tree, the Roadmap, the open page, its parent's list of children,
 *  the Todos board. Invalidating them one call site at a time is how a screen
 *  ends up stale after an edit somewhere else, which is exactly what the user
 *  hit. Mutations call this instead of listing keys.
 */
const KEYS = [
  'subjects',      // the sidebar tree
  'page',          // whichever page is open, and its children
  'roadmap',
  'todo-board',
  'note',          // the editor's copy of a note
  'note-panel',    // checklist / concepts / links
  'notes',
  'notes-by-date',
  'calendar',
  'lesson-checklist',
  'pipeline-pending',
  'resources',
  'resource-groups',
  'tags',
  'study-next',
  'progress',
  'recall',
  'practice-available',
]

export function useRefreshEverything() {
  const qc = useQueryClient()
  return async () => {
    await Promise.all(KEYS.map((key) => qc.invalidateQueries({ queryKey: [key] })))
  }
}
