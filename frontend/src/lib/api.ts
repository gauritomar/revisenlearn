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

export type PipelineJob = {
  id: number
  name: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  stage: string | null
  subject_id: number | null
  block_count: number
  concepts_created: number
  concepts_updated: number
  concepts_merged: number
  edges_proposed: number
  mcqs_generated: number
  error_text: string | null
  retry_count: number
  created_at: string
  started_at: string | null
  finished_at: string | null
}
export type LLMRunRow = {
  id: number
  task: string
  model: string
  prompt_version: string | null
  request_mode: string
  input_tokens: number
  output_tokens: number
  cached_tokens: number
  estimated_cost_usd: number | null
  success: boolean
  error_text: string | null
  created_at: string
}
export type JobDetail = {
  job: PipelineJob
  stats: {
    llm_calls: number
    input_tokens: number
    output_tokens: number
    cached_tokens: number
    estimated_cost_usd: number
    unpriced_calls: number
    failed_calls: number
  }
  runs: LLMRunRow[]
}

export type PracticeOption = { id: string; text: string }
export type PracticeQuestion = {
  item_id: number
  position: number
  mcq_id: number
  concept_id: number
  concept_name: string
  dimension: string
  stem: string
  options: PracticeOption[]
  selection_bucket: string | null
}
export type PracticeFeedback = {
  is_correct: boolean
  correct_option_id: string
  explanation: string | null
  distractor_rationales: Record<string, string>
  retired: boolean
  consecutive_correct: number
}
export type PracticeSummary = {
  session_id: number
  planned_count: number
  completed_count: number
  correct_count: number
  duration_ms: number | null
  finished: boolean
  per_concept: Array<{
    concept_id: number
    concept_name: string
    asked: number
    correct: number
  }>
  missed_mcq_ids: number[]
}

export type ProseQuestion = {
  item_id: number
  position: number
  question_id: number
  concept_id: number
  concept_name: string
  dimension: string
  question_text: string
  expected_length: string
  selection_bucket: string | null
}
export type ProseFeedback = {
  attempt_id: number
  question_id: number
  rating: string
  hit_ratio: number
  key_point_hits: Array<{ point: string; hit: boolean }>
  factually_incorrect_claims: string[]
  misconceptions: string[]
  feedback: string
  expected_answer: string | null
  due_at: string | null
  skipped: boolean
  overridden?: boolean
}
export type RevisionSummary = {
  session_id: number
  planned_count: number
  completed_count: number
  answered: number
  duration_ms: number | null
  finished: boolean
  per_concept: Array<{
    concept_id: number
    concept_name: string
    answered: number
    ratings: string[]
  }>
  retest_offers: Array<{
    attempt_id: number
    question_id: number
    concept_name: string
    dimension: string
    rating: string
    question_text: string
  }>
}
export type RevisionDashboard = {
  due_count: number
  overdue_count: number
  new_count: number
  reviews_logged: number
  weak_areas: Array<{
    concept_id: number
    concept_name: string
    dimension: string
    last_rating: string
  }>
  sizes: number[]
  default_size: number
}

export type RoadmapItem = { id: number; title: string; done: boolean; position: number }
export type RoadmapLesson = {
  id: number
  name: string
  status: string
  position: number
  topic_id: number
  subtopic_id: number | null
  pct: number | null
  items: RoadmapItem[]
}
export type RoadmapSubtopic = { id: number; name: string; pct: number | null; lessons: RoadmapLesson[] }
export type RoadmapTopic = {
  id: number
  name: string
  pct: number | null
  subtopics: RoadmapSubtopic[]
  lessons: RoadmapLesson[]
}
export type RoadmapSubject = {
  id: number
  name: string
  colour: string | null
  pct: number | null
  topics: RoadmapTopic[]
}
export type TodoEntry = {
  kind: 'todo' | 'lesson' | 'lesson_item'
  id: number
  title: string
  done: boolean
  due_date: string | null
  subject_id: number | null
  topic_id: number | null
  lesson_id: number | null
  context: string | null
}

export type GraphNode = {
  id: number
  name: string
  status: string
  badge: string
  mastery: number | null
  importance: number
  difficulty: number | null
  subject: string | null
  topic: string | null
  subtopic: string | null
  dimmed: boolean
}
export type GraphEdge = {
  id: number
  source: number
  target: number
  relation_type: string
  status: string
  confidence: number | null
  created_by: string
  job_id: number | null
  dimmed: boolean
}
export type GraphPayload = {
  view: string
  nodes: GraphNode[]
  edges: GraphEdge[]
  counts: { nodes: number; edges: number }
}
export type ProposedEdge = {
  id: number
  source_id: number
  target_id: number
  source_name: string
  target_name: string
  relation_type: string
  confidence: number | null
  created_by: string
  job_id: number | null
  cycle_conflict: boolean
  cycle_path: number[]
}
export type ConceptDetail = {
  id: number
  canonical_name: string
  definition: string | null
  status: string
  importance: number | null
  difficulty: number | null
  coverage_profile: Record<string, boolean>
  aliases: Array<{ id: number; alias: string; source: string }>
  sources: Array<{ note_id: number; note_block_id: number; text: string | null; invalidated: boolean }>
  edges: Array<{ id: number; direction: string; other_id: number; other_name: string; relation_type: string; status: string }>
  review_items: Array<{ dimension: string; reps: number; lapses: number; suspended: boolean; due_at: string | null }>
  history: Array<{ dimension: string; rating: number | null; created_at: string | null }>
  mastery: { badge: string; mastery: number | null }
  cost: { generations: number; input_tokens: number; output_tokens: number; estimated_cost_usd: number }
}

export type MergeRow = {
  id: number
  merged_from_id: number
  merged_into_id: number
  merged_from_name: string
  merged_into_name: string
  similarity: number | null
  decided_by: string | null
  created_at: string
  reverted_at: string | null
}
export type ConceptRow = {
  id: number
  name?: string
  canonical_name?: string
  status?: string
  importance?: number | null
}

export type UsageSummary = {
  month: string
  disclaimer: string
  billing_console_url: string
  spent_usd: number
  spent_gbp: number | null
  fx_rate: number | null
  calls: number
  input_tokens: number
  output_tokens: number
  cached_tokens: number
  unpriced_calls: number
  cap: {
    month: string
    spent_usd: number
    cap_usd: number | null
    ratio: number | null
    level: 'none' | 'ok' | 'warn' | 'over'
    requires_confirmation: boolean
    unpriced_calls: number
  }
  daily: Array<{ date: string; usd: number }>
  by_task: Array<{
    task: string
    calls: number
    input_tokens: number
    output_tokens: number
    usd: number
  }>
}
export type UsageConcept = {
  concept_id: number
  concept_name: string
  generations: number
  tokens: number
  usd: number
  gbp: number | null
}
export type Progress = {
  concepts: number
  stale_concepts: number
  reviews: number
  mcq_answers: number
  mcq_correct: number
  prose_answers: number
  mastery_distribution: Record<string, number>
  reviews_by_day: Array<{ date: string; count: number }>
}

export type PendingBlock = {
  note_block_id: number
  note_id: number
  note_title: string
  block_type: string
  snippet: string
  state: string
}

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

  pending: (subjectId?: number) =>
    request<{ unprocessed_blocks: number; subject_id: number | null }>(
      `/api/pipeline/pending${subjectId ? `?subject_id=${subjectId}` : ''}`,
    ),
  pendingPreview: (subjectId?: number) =>
    request<{
      unprocessed_blocks: number
      estimated_tokens: number
      blocks: PendingBlock[]
    }>(
      `/api/pipeline/pending?preview=true${subjectId ? `&subject_id=${subjectId}` : ''}`,
    ),
  runPipeline: (subject_id?: number | null) =>
    request<PipelineJob>('/api/pipeline/run', {
      method: 'POST',
      body: JSON.stringify({ subject_id: subject_id ?? null }),
    }),
  jobs: () => request<PipelineJob[]>('/api/pipeline/jobs'),
  job: (id: number) => request<JobDetail>(`/api/pipeline/jobs/${id}`),
  retryJob: (id: number) =>
    request<PipelineJob>(`/api/pipeline/jobs/${id}/retry`, { method: 'POST' }),

  practiceAvailable: () =>
    request<{ active_mcqs: number; concepts: number; never_served: number }>(
      '/api/practice/available',
    ),
  startPractice: (count: number, scope?: Record<string, unknown>) =>
    request<{ id: number; planned_count: number }>('/api/practice/session', {
      method: 'POST',
      body: JSON.stringify({ count, scope: scope ?? null }),
    }),
  nextQuestion: (id: number) =>
    request<{ done: boolean; question?: PracticeQuestion; summary?: PracticeSummary }>(
      `/api/practice/session/${id}/next`,
    ),
  answerPractice: (
    id: number,
    body: { item_id: number; selected_option_id: string; response_ms?: number },
  ) =>
    request<PracticeFeedback>(`/api/practice/session/${id}/answer`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  finishPractice: (id: number) =>
    request<PracticeSummary>(`/api/practice/session/${id}/finish`, {
      method: 'POST',
    }),
  practiceSummary: (id: number) =>
    request<PracticeSummary>(`/api/practice/session/${id}/summary`),

  revisionDashboard: () => request<RevisionDashboard>('/api/revision/dashboard'),
  startRevision: (count: number) =>
    request<{ id: number; planned_count: number }>('/api/revision/session', {
      method: 'POST',
      body: JSON.stringify({ count }),
    }),
  nextProseQuestion: (id: number) =>
    request<{ done: boolean; question?: ProseQuestion; summary?: RevisionSummary }>(
      `/api/revision/session/${id}/next`,
    ),
  answerProse: (
    id: number,
    body: { item_id: number; answer: string; response_ms?: number },
  ) =>
    request<ProseFeedback>(`/api/revision/session/${id}/answer`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  skipProse: (id: number, item_id: number) =>
    request<ProseFeedback>(`/api/revision/session/${id}/skip`, {
      method: 'POST',
      body: JSON.stringify({ item_id }),
    }),
  overrideProse: (id: number, attempt_id: number, direction: string) =>
    request<{ rating: string; changed: boolean }>(
      `/api/revision/session/${id}/override`,
      { method: 'POST', body: JSON.stringify({ attempt_id, direction }) },
    ),
  startRetest: (id: number, attempt_id: number, mode: string) =>
    request<Record<string, unknown>>(`/api/revision/session/${id}/retest`, {
      method: 'POST',
      body: JSON.stringify({ attempt_id, mode }),
    }),
  answerRetest: (
    id: number,
    body: { question_id: number; retest_of_attempt_id: number; answer: string },
  ) =>
    request<ProseFeedback>(`/api/revision/session/${id}/retest/answer`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  finishRevision: (id: number) =>
    request<RevisionSummary>(`/api/revision/session/${id}/finish`, {
      method: 'POST',
    }),

  roadmap: () => request<{ subjects: RoadmapSubject[] }>('/api/roadmap'),
  createLesson: (body: Record<string, unknown>) =>
    request<RoadmapLesson>('/api/lessons', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateLesson: (id: number, body: Record<string, unknown>) =>
    request<RoadmapLesson>(`/api/lessons/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  deleteLesson: (id: number) =>
    request<void>(`/api/lessons/${id}`, { method: 'DELETE' }),
  createLessonItem: (lessonId: number, title: string) =>
    request<RoadmapItem>(`/api/lessons/${lessonId}/items`, {
      method: 'POST',
      body: JSON.stringify({ title }),
    }),
  updateLessonItem: (lessonId: number, itemId: number, body: Record<string, unknown>) =>
    request<RoadmapItem>(`/api/lessons/${lessonId}/items/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  todoBoard: (params: Record<string, string | number | boolean> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)]),
    ).toString()
    return request<{ entries: TodoEntry[]; hide_completed: boolean }>(
      `/api/todos/board${qs ? `?${qs}` : ''}`,
    )
  },
  createTodo: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/todos', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateTodo: (id: number, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/todos/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  graph: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)]),
    ).toString()
    return request<GraphPayload>(`/api/graph${qs ? `?${qs}` : ''}`)
  },
  graphQueues: () => request<Record<string, number>>('/api/graph/queues'),
  mergeQueue: () => request<MergeRow[]>('/api/graph/merge-queue'),
  proposedEdges: () => request<ProposedEdge[]>('/api/graph/edges?status=proposed'),
  staleConcepts: () => request<ConceptRow[]>('/api/graph/stale'),
  autoMerged: () => request<MergeRow[]>('/api/graph/auto-merged'),
  orphans: () => request<ConceptRow[]>('/api/graph/orphans'),
  doMerge: (from: number, into: number) =>
    request<Record<string, unknown>>('/api/graph/merge', {
      method: 'POST',
      body: JSON.stringify({ merged_from_id: from, merged_into_id: into }),
    }),
  rejectMerge: (id: number) =>
    request<Record<string, unknown>>(`/api/graph/merge/${id}/reject`, { method: 'POST' }),
  revertMerge: (id: number) =>
    request<Record<string, unknown>>(`/api/graph/merge/${id}/revert`, { method: 'POST' }),
  acceptEdge: (id: number) =>
    request<Record<string, unknown>>(`/api/graph/edges/${id}/accept`, { method: 'POST' }),
  rejectEdge: (id: number) =>
    request<Record<string, unknown>>(`/api/graph/edges/${id}/reject`, { method: 'POST' }),
  flipEdge: (id: number) =>
    request<Record<string, unknown>>(`/api/graph/edges/${id}/flip`, { method: 'POST' }),
  graphConcept: (id: number) => request<ConceptDetail>(`/api/graph/concepts/${id}`),
  editConcept: (id: number, body: Record<string, unknown>) =>
    request<ConceptDetail>(`/api/graph/concepts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  usageSummary: () => request<UsageSummary>('/api/usage/summary'),
  usageByConcept: (limit = 50) =>
    request<UsageConcept[]>(`/api/usage/by-concept?limit=${limit}`),
  usageByHierarchy: () =>
    request<{
      by_subject: Array<{ subject: string; usd: number }>
      by_topic: Array<{ subject: string; topic: string; usd: number }>
    }>('/api/usage/by-hierarchy'),
  progress: () => request<Progress>('/api/progress'),
  interviewMode: () => request<{ enabled: boolean }>('/api/revision/interview-mode'),
  setInterviewMode: (enabled: boolean) =>
    request<{ enabled: boolean; items_changed: number }>(
      '/api/revision/interview-mode',
      { method: 'POST', body: JSON.stringify({ enabled }) },
    ),
  mockRound: () =>
    request<{ id: number; planned_count: number }>('/api/revision/mock-round', {
      method: 'POST',
      body: JSON.stringify({ count: 5 }),
    }),

  settings: () =>
    request<{ values: Record<string, unknown>; api_key: { present: boolean; source: string } }>(
      '/api/settings',
    ),
  patchSettings: (values: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/settings', {
      method: 'PATCH',
      body: JSON.stringify({ values }),
    }),
  adaptiveCoverage: () =>
    request<{ added_debug: number[]; added_synthesis: number[] }>(
      '/api/maintenance/adaptive-coverage',
      { method: 'POST' },
    ),

  providers: () =>
    request<{
      provider: string
      tasks: Record<string, { model: string; thinking_level?: string; mode: string }>
      source: string
    }>('/api/providers'),
  practiceDefaults: () =>
    request<{ default: number; options: number[] }>('/api/practice/defaults'),

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
