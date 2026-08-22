/** Thin API client. Same origin in production; Vite proxies in --dev. */

export type Subtopic = { id: number; topic_id: number; name: string; sort_order: number }
export type Topic = { id: number; subject_id: number; name: string; sort_order: number; subtopics: Subtopic[] }
export type Subject = { id: number; name: string; colour: string | null; sort_order: number; topics: Topic[] }

export type BlockState = 'unprocessed' | 'processed' | 'stale'
export type Block = {
  id: number
  note_id: number
  position: number
  block_type: string
  text: string
  content_hash: string
  processed_hash: string | null
  state: BlockState
}
export type Note = {
  id: number
  title: string
  study_date: string
  subject_id: number | null
  topic_id: number | null
  subtopic_id: number | null
  resource_id: number | null
  created_at: string
  updated_at: string
  blocks: Block[]
  counts: { processed: number; new: number; edited: number }
}


export type ResourceStatus = 'inbox' | 'next' | 'in_progress' | 'completed' | 'archived'

export type Resource = {
  id: number
  title: string
  url: string | null
  resource_type: string
  description: string | null
  status: ResourceStatus
  priority: number
  subject_id: number | null
  topic_id: number | null
  subtopic_id: number | null
  progress_pct: number
  progress_note: string | null
  created_at: string
  last_opened_at: string | null
  completed_at: string | null
}

export type TitleProbe = { title: string | null; resource_type: string }

export type Placement = {
  subject_id?: number | null
  topic_id?: number | null
  subtopic_id?: number | null
}

export type CalendarPill = { topic_id: number; name: string; colour: string | null }
export type CalendarDay = { date: string; note_count: number; topics: CalendarPill[] }
export type CalendarMonth = { month: string; days: CalendarDay[] }

export type BackupEntry = {
  name: string
  path: string
  taken_at: string
  size_bytes: number
}
export type BackupList = {
  directory: string
  backups: BackupEntry[]
  total_bytes: number
}
export type BackupRun = { created: BackupEntry; pruned: string[] }
export type ExportResult = { path: string; note_count: number; file_count: number }

export type SearchHit = {
  kind: 'note_block' | 'concept'
  note_id: number | null
  note_title: string | null
  note_block_id: number | null
  concept_id: number | null
  title: string
  snippet: string
  study_date: string | null
}

export type AppMeta = {
  app_name: string
  version: string
  phase: number
  api_key: { present: boolean; source: string }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${body.slice(0, 300)}`)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  meta: () => request<AppMeta>('/api/meta'),

  subjects: () => request<Subject[]>('/api/subjects'),
  createSubject: (name: string) =>
    request<Subject>('/api/subjects', { method: 'POST', body: JSON.stringify({ name }) }),
  createTopic: (subject_id: number, name: string) =>
    request<Topic>('/api/topics', { method: 'POST', body: JSON.stringify({ subject_id, name }) }),
  createSubtopic: (topic_id: number, name: string) =>
    request<Subtopic>('/api/subtopics', { method: 'POST', body: JSON.stringify({ topic_id, name }) }),

  ensureNote: (subtopic_id: number, study_date?: string) =>
    request<Note>('/api/notes/ensure', {
      method: 'POST',
      body: JSON.stringify({ subtopic_id, study_date }),
    }),
  note: (id: number) => request<Note>(`/api/notes/${id}`),
  createNote: (body: Record<string, unknown>) =>
    request<Note>('/api/notes', { method: 'POST', body: JSON.stringify(body) }),
  updateNote: (id: number, body: Record<string, unknown>) =>
    request<Note>(`/api/notes/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  saveBlocks: (id: number, blocks: Array<{ id?: number | null; position: number; block_type: string; text: string }>) =>
    request<Note>(`/api/notes/${id}/blocks`, { method: 'PUT', body: JSON.stringify({ blocks }) }),

  resources: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)]),
    ).toString()
    return request<Resource[]>(`/api/resources${qs ? `?${qs}` : ''}`)
  },
  resource: (id: number) => request<Resource>(`/api/resources/${id}`),
  studyNext: (limit = 5) => request<Resource[]>(`/api/resources/study-next?limit=${limit}`),
  lastUsed: () => request<Placement>('/api/resources/last-used'),
  probeTitle: (url: string) =>
    request<TitleProbe>('/api/resources/probe-title', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),
  createResource: (body: Record<string, unknown>) =>
    request<Resource>('/api/resources', { method: 'POST', body: JSON.stringify(body) }),
  updateResource: (id: number, body: Record<string, unknown>) =>
    request<Resource>(`/api/resources/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  deleteResource: (id: number) =>
    request<void>(`/api/resources/${id}`, { method: 'DELETE' }),
  openResource: (id: number) =>
    request<Resource>(`/api/resources/${id}/open`, { method: 'POST' }),

  ensureResourceNote: (resource_id: number, study_date?: string) =>
    request<Note>('/api/notes/ensure', {
      method: 'POST',
      body: JSON.stringify({ resource_id, study_date }),
    }),
  notesByDate: (date: string) => request<Note[]>(`/api/notes/by-date/${date}`),
  notes: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)]),
    ).toString()
    return request<Note[]>(`/api/notes${qs ? `?${qs}` : ''}`)
  },

  calendar: (month: string) => request<CalendarMonth>(`/api/notes/calendar/${month}`),

  backupList: () => request<BackupList>('/api/backup/list'),
  backupNow: () => request<BackupRun>('/api/backup/now', { method: 'POST' }),
  exportMarkdown: (destination?: string) =>
    request<ExportResult>('/api/export/markdown', {
      method: 'POST',
      body: JSON.stringify(destination ? { destination } : {}),
    }),

  search: (q: string) =>
    request<{ query: string; hits: SearchHit[] }>(`/api/search?q=${encodeURIComponent(q)}`),
}

/** Creates subject → topic → subtopic, reusing any level that already exists
 *  by (case-insensitive) name. Keeps the add flow to one dialog. */
export async function createBranch(
  subjects: Subject[],
  subjectName: string,
  topicName: string,
  subtopicName: string,
): Promise<{ subjectId: number; topicId: number | null; subtopicId: number | null }> {
  const eq = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase()

  let subject = subjects.find((s) => eq(s.name, subjectName))
  const subjectId = subject ? subject.id : (await api.createSubject(subjectName.trim())).id

  if (!topicName.trim()) return { subjectId, topicId: null, subtopicId: null }

  const existingTopic = subject?.topics.find((t) => eq(t.name, topicName))
  const topicId = existingTopic ? existingTopic.id : (await api.createTopic(subjectId, topicName.trim())).id

  if (!subtopicName.trim()) return { subjectId, topicId, subtopicId: null }

  const existingSub = existingTopic?.subtopics.find((s) => eq(s.name, subtopicName))
  const subtopicId = existingSub ? existingSub.id : (await api.createSubtopic(topicId, subtopicName.trim())).id

  return { subjectId, topicId, subtopicId }
}
