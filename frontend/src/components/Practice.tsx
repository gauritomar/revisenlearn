import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { api, type PracticeFeedback, type PracticeQuestion, type PracticeSummary } from '../lib/api'
import { useUI } from '../store/ui'

/** Quick Practice (spec §9.1 **[LOCKED]**).
 *
 *  Scope and count picker → MCQ runner with a stopwatch → summary with a
 *  per-concept breakdown and "practise the ones I missed".
 *
 *  §14.4: `1`–`4` select an option, `Space` moves to the next question.
 *  The stopwatch counts **up**, never down — §9.6 wants this to feel
 *  lower-stakes, not timed.
 */
const COUNTS = [20, 30, 50]

type Stage = 'picker' | 'running' | 'summary'

export function Practice() {
  const [stage, setStage] = useState<Stage>('picker')
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [summary, setSummary] = useState<PracticeSummary | null>(null)
  const pending = useUI((s) => s.pendingPracticeSession)
  const setPendingPractice = useUI((s) => s.setPendingPractice)

  // A session made elsewhere — "practise what you studied three days ago" —
  // arrives already built, so the picker would only be in the way.
  useEffect(() => {
    if (pending === null) return
    setSessionId(pending)
    setStage('running')
    setPendingPractice(null)
  }, [pending, setPendingPractice])

  if (stage === 'running' && sessionId !== null) {
    return (
      <Runner
        sessionId={sessionId}
        onFinish={(result) => {
          setSummary(result)
          setStage('summary')
        }}
      />
    )
  }

  if (stage === 'summary' && summary) {
    return (
      <Summary
        summary={summary}
        onAgain={() => {
          setSummary(null)
          setSessionId(null)
          setStage('picker')
        }}
      />
    )
  }

  return (
    <Picker
      onStart={(id) => {
        setSessionId(id)
        setStage('running')
      }}
    />
  )
}

// --------------------------------------------------------------------------

function Picker({ onStart }: { onStart: (sessionId: number) => void }) {
  const [count, setCount] = useState(20)
  const { data: available } = useQuery({
    queryKey: ['practice-available'],
    queryFn: api.practiceAvailable,
  })

  const start = useMutation({
    mutationFn: () => api.startPractice(count),
    onSuccess: (row) => onStart(row.id),
  })

  const pool = available?.active_mcqs ?? 0

  return (
    <div data-testid="practice-picker" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <h2 className="text-xl font-semibold tracking-tight text-ink">Quick Practice</h2>
      <p className="mt-1 text-[0.875rem] leading-relaxed text-muted">
        Multiple choice, for volume and warm-up. Results feed your practice
        statistics — they never move a review date.
      </p>

      {pool === 0 ? (
        <p data-testid="practice-empty" className="mt-5 rounded-lg border border-dashed border-line bg-surface p-8 text-center text-[0.875rem] text-faint">
          No questions yet. Write some notes and press Process notes; questions
          are generated from your concepts.
        </p>
      ) : (
        <>
          <p className="mt-4 text-[0.8125rem] text-muted" data-testid="practice-available">
            {pool} active question{pool === 1 ? '' : 's'} across{' '}
            {available?.concepts ?? 0} concept
            {available?.concepts === 1 ? '' : 's'}
            {available && available.never_served > 0
              ? ` · ${available.never_served} never seen`
              : ''}
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            {COUNTS.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setCount(n)}
                data-testid={`count-${n}`}
                className={[
                  'rounded-md border px-3 py-1.5 text-[0.8125rem] transition',
                  count === n
                    ? 'border-accent bg-accent-wash font-medium text-accent-deep'
                    : 'border-line text-ink-soft hover:bg-sunken',
                ].join(' ')}
              >
                {n}
              </button>
            ))}
            <label className="flex items-center gap-1.5 text-[0.8125rem] text-muted">
              or
              <input
                type="number"
                min={1}
                max={200}
                value={count}
                data-testid="count-custom"
                onChange={(e) => setCount(Math.max(1, Number(e.target.value) || 1))}
                className="w-16 rounded-md border border-line bg-paper px-2 py-1 text-[0.8125rem] text-ink outline-none focus:border-accent"
              />
            </label>
          </div>

          <button
            type="button"
            onClick={() => start.mutate()}
            disabled={start.isPending}
            data-testid="start-practice"
            className="mt-5 rounded-md bg-accent px-4 py-2 text-[0.875rem] font-medium text-white transition hover:bg-accent-deep disabled:opacity-50"
          >
            {start.isPending ? 'Starting…' : `Practise ${count}`}
          </button>

          {start.isError && (
            <p data-testid="practice-error" className="mt-3 text-[0.8125rem] text-stale">
              {(start.error as Error).message.slice(0, 160)}
            </p>
          )}
        </>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------

function Runner({ sessionId, onFinish }: {
  sessionId: number
  onFinish: (summary: PracticeSummary) => void
}) {
  const [question, setQuestion] = useState<PracticeQuestion | null>(null)
  const [feedback, setFeedback] = useState<PracticeFeedback | null>(null)
  const [answered, setAnswered] = useState(0)
  const [planned, setPlanned] = useState(0)
  const shownAt = useRef<number>(Date.now())

  const load = useCallback(async () => {
    const next = await api.nextQuestion(sessionId)
    if (next.done) {
      onFinish(await api.finishPractice(sessionId))
      return
    }
    setQuestion(next.question ?? null)
    setFeedback(null)
    shownAt.current = Date.now()
  }, [sessionId, onFinish])

  useEffect(() => {
    void api.practiceSummary(sessionId).then((s) => setPlanned(s.planned_count))
    void load()
  }, [sessionId, load])

  const submit = useCallback(
    async (optionId: string) => {
      if (!question || feedback) return
      const result = await api.answerPractice(sessionId, {
        item_id: question.item_id,
        selected_option_id: optionId,
        response_ms: Date.now() - shownAt.current,
      })
      setFeedback(result)
      setAnswered((n) => n + 1)
    },
    [question, feedback, sessionId],
  )

  // Spec §14.4 — 1-4 select an option, Space moves on.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return
      if (!feedback && question && ['1', '2', '3', '4'].includes(e.key)) {
        const option = question.options[Number(e.key) - 1]
        if (option) {
          e.preventDefault()
          void submit(option.id)
        }
      }
      if (feedback && e.key === ' ') {
        e.preventDefault()
        void load()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [feedback, question, submit, load])

  if (!question) {
    return <div className="p-6 text-[0.8125rem] text-faint">Loading…</div>
  }

  return (
    <div data-testid="practice-runner" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <div className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-line-soft pb-3">
        <span className="text-[0.8125rem] tabular-nums text-muted" data-testid="practice-progress">
          {answered + (feedback ? 0 : 1)} / {planned || '—'}
        </span>
        <span className="truncate text-[0.8125rem] text-ink-soft" data-testid="practice-concept">
          {question.concept_name}
        </span>
        <Stopwatch />
      </div>

      <p data-testid="practice-stem" className="text-[1.0625rem] leading-relaxed text-ink">
        {question.stem}
      </p>

      <ul className="mt-4 space-y-2">
        {question.options.map((option, index) => {
          const isCorrect = feedback && option.id === feedback.correct_option_id
          const isWrongPick =
            feedback && !feedback.is_correct && option.id !== feedback.correct_option_id
          return (
            <li key={option.id}>
              <button
                type="button"
                disabled={!!feedback}
                onClick={() => void submit(option.id)}
                data-testid={`option-${option.id}`}
                data-correct={isCorrect ? 'true' : undefined}
                className={[
                  'flex w-full items-baseline gap-2.5 rounded-lg border p-3 text-left text-[0.9375rem] transition',
                  isCorrect
                    ? 'border-mastery-3 bg-mastery-3/10 text-ink'
                    : isWrongPick
                      ? 'border-line text-muted'
                      : 'border-line text-ink hover:border-accent hover:bg-accent-wash',
                  feedback ? 'cursor-default' : '',
                ].join(' ')}
              >
                <kbd className="shrink-0 rounded border border-line px-1.5 text-[0.6875rem] text-faint">
                  {index + 1}
                </kbd>
                <span className="min-w-0 flex-1">{option.text}</span>
              </button>
            </li>
          )
        })}
      </ul>

      {feedback && (
        <div
          data-testid="practice-feedback"
          data-correct={feedback.is_correct ? 'true' : 'false'}
          className="mt-4 rounded-lg border border-line bg-surface p-3"
        >
          <p
            className={`text-[0.875rem] font-medium ${
              feedback.is_correct ? 'text-mastery-4' : 'text-stale'
            }`}
          >
            {feedback.is_correct ? 'Correct' : 'Not quite'}
          </p>
          <p className="mt-1 text-[0.875rem] leading-relaxed text-ink-soft">
            {feedback.explanation}
          </p>
          <button
            type="button"
            onClick={() => void load()}
            data-testid="practice-next"
            className="mt-3 rounded-md bg-accent px-3 py-1.5 text-[0.8125rem] font-medium text-white transition hover:bg-accent-deep"
          >
            Next <kbd className="ml-1 text-[0.6875rem] opacity-70">Space</kbd>
          </button>
        </div>
      )}
    </div>
  )
}

/** Spec §9.1 — "a session stopwatch (elapsed, not counting down)". */
function Stopwatch() {
  const [elapsed, setElapsed] = useState(0)
  const start = useRef(Date.now())

  useEffect(() => {
    const id = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - start.current) / 1000)),
      1000,
    )
    return () => window.clearInterval(id)
  }, [])

  const minutes = Math.floor(elapsed / 60)
  const seconds = elapsed % 60
  return (
    <span
      data-testid="practice-stopwatch"
      className="ml-auto text-[0.8125rem] tabular-nums text-faint"
    >
      {minutes}:{String(seconds).padStart(2, '0')}
    </span>
  )
}

// --------------------------------------------------------------------------

function Summary({ summary, onAgain }: {
  summary: PracticeSummary
  onAgain: () => void
}) {
  const pct = summary.completed_count
    ? Math.round((summary.correct_count / summary.completed_count) * 100)
    : 0
  const minutes = Math.floor((summary.duration_ms ?? 0) / 60000)
  const seconds = Math.floor(((summary.duration_ms ?? 0) % 60000) / 1000)

  return (
    <div data-testid="practice-summary" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <h2 className="text-xl font-semibold tracking-tight text-ink">Session complete</h2>

      <div className="mt-4 grid grid-cols-3 gap-3">
        <Stat label="Correct" value={`${summary.correct_count}/${summary.completed_count}`} />
        <Stat label="Score" value={`${pct}%`} />
        <Stat label="Time" value={`${minutes}:${String(seconds).padStart(2, '0')}`} />
      </div>

      <h3 className="mt-6 text-[0.8125rem] font-semibold tracking-tight text-ink">
        By concept
      </h3>
      <ul className="mt-2 space-y-1" data-testid="summary-concepts">
        {summary.per_concept.map((entry) => (
          <li
            key={entry.concept_id}
            className="flex items-baseline gap-2 rounded-md px-2 py-1.5 odd:bg-paper"
          >
            <span className="min-w-0 flex-1 truncate text-[0.8125rem] text-ink">
              {entry.concept_name}
            </span>
            <span className="shrink-0 text-[0.8125rem] tabular-nums text-muted">
              {entry.correct}/{entry.asked}
            </span>
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={onAgain}
        data-testid="practice-again"
        className="mt-6 rounded-md bg-accent px-4 py-2 text-[0.875rem] font-medium text-white transition hover:bg-accent-deep"
      >
        Practise again
      </button>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <div className="text-xl font-semibold tabular-nums text-ink">{value}</div>
      <div className="mt-0.5 text-[0.6875rem] text-muted">{label}</div>
    </div>
  )
}
