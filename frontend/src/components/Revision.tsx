import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { StudySets } from './StudySets'
import { Spinner, Waiting } from './Waiting'
import {
  api,
  type ProseFeedback,
  type ProseQuestion,
  type RevisionSummary,
  type StudySet,
} from '../lib/api'

/** Revision — the prose loop (spec §9.2–§9.6 **[LOCKED]**).
 *
 *  §9.6 governs every choice of wording and weight here:
 *  the due count is neutral and never a badge; the default session is 5; the
 *  skip button is as prominent as submit; a session of one is complete; the
 *  summary says what was done, not what was left.
 */
type Stage = 'dashboard' | 'running' | 'summary'

export function Revision() {
  const [stage, setStage] = useState<Stage>('dashboard')
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [summary, setSummary] = useState<RevisionSummary | null>(null)

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
  if (stage === 'summary' && summary && sessionId !== null) {
    return (
      <Summary
        sessionId={sessionId}
        summary={summary}
        onDone={() => {
          setSummary(null)
          setSessionId(null)
          setStage('dashboard')
        }}
      />
    )
  }
  return (
    <Dashboard
      onStart={(id) => {
        setSessionId(id)
        setStage('running')
      }}
    />
  )
}

// --------------------------------------------------------------------------

function Dashboard({ onStart }: { onStart: (id: number) => void }) {
  const { data } = useQuery({
    queryKey: ['revision-dashboard'],
    queryFn: api.revisionDashboard,
  })
  const [count, setCount] = useState(5)

  const start = useMutation({
    mutationFn: () => api.startRevision(count),
    onSuccess: (row) => onStart(row.id),
  })

  // "On the Revision panel also I should have topic-wise / subtopic revision
  // ready." Same places as Practice, scoped the same way.
  const [startingSet, setStartingSet] = useState<number | null>(null)
  const startSet = useMutation({
    mutationFn: (set: StudySet) => {
      setStartingSet(set.id)
      return api.startRevision(Math.min(10, Math.max(1, set.due_count)),
                               set.concept_ids)
    },
    onSuccess: (row) => onStart(row.id),
    onSettled: () => setStartingSet(null),
  })

  const due = data?.due_count ?? 0

  return (
    <div data-testid="revision-dashboard" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <h2 className="text-xl font-semibold tracking-tight text-ink">Revision</h2>
      <p className="mt-1 text-[0.875rem] leading-relaxed text-muted">
        Written answers, marked against key points. This is the part that moves
        your schedule.
      </p>

      {/* §9.6 — neutral grey count. No badge, no red, no exclamation. */}
      <div className="mt-4 grid grid-cols-3 gap-3">
        <Stat label="Ready to review" value={due} testid="revision-due" />
        <Stat label="Never reviewed" value={data?.new_count ?? 0} />
        <Stat label="Reviews logged" value={data?.reviews_logged ?? 0} />
      </div>

      <section className="mt-5">
        <h3 className="text-[0.6875rem] font-semibold uppercase tracking-[0.09em] text-muted">
          By subtopic
        </h3>
        <p className="mt-1 text-[0.75rem] text-faint">
          Revise one place at a time, most recently written first.
        </p>
        <StudySets kind="revision" onPick={(set) => startSet.mutate(set)}
                   busyFor={startingSet} />
      </section>

      {due === 0 ? (
        <p data-testid="revision-empty" className="mt-5 rounded-lg border border-dashed border-line bg-surface p-8 text-center text-[0.875rem] text-faint">
          Nothing is ready yet. Concepts become reviewable once you have
          processed some notes.
        </p>
      ) : (
        <>
          <h3 className="mt-6 text-[0.6875rem] font-semibold uppercase tracking-[0.09em] text-muted">
            Or everything due
          </h3>
          <div className="mt-5 flex flex-wrap items-center gap-2">
            {[5, 10, 20].map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setCount(n)}
                data-testid={`revision-count-${n}`}
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
                max={100}
                value={count}
                data-testid="revision-count-custom"
                onChange={(e) => setCount(Math.max(1, Number(e.target.value) || 1))}
                className="w-16 rounded-md border border-line bg-paper px-2 py-1 text-[0.8125rem] text-ink outline-none focus:border-accent"
              />
            </label>
          </div>

          <button
            type="button"
            onClick={() => start.mutate()}
            disabled={start.isPending}
            data-testid="start-revision"
            className="mt-5 flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-[0.875rem] font-medium text-white transition hover:bg-accent-deep disabled:opacity-50"
          >
            {start.isPending && <Spinner className="text-white" />}
            {start.isPending ? 'Building the session…' : `Review ${count}`}
          </button>
          <p className="mt-2 text-[0.75rem] text-faint">
            Five is a real session. Stopping after one is a real session too.
          </p>

          {start.isError && (
            <p data-testid="revision-error" className="mt-3 text-[0.8125rem] text-stale">
              {(start.error as Error).message.slice(0, 200)}
            </p>
          )}
        </>
      )}

      {(data?.weak_areas.length ?? 0) > 0 && (
        <>
          <h3 className="mt-7 text-[0.8125rem] font-semibold tracking-tight text-ink">
            Worth another look
          </h3>
          <ul className="mt-2 space-y-1" data-testid="weak-areas">
            {data!.weak_areas.map((entry, i) => (
              <li
                key={`${entry.concept_id}-${entry.dimension}-${i}`}
                className="flex items-baseline gap-2 rounded-md px-2 py-1.5 odd:bg-paper"
              >
                <span className="min-w-0 flex-1 truncate text-[0.8125rem] text-ink">
                  {entry.concept_name}
                </span>
                <span className="shrink-0 text-[0.6875rem] uppercase tracking-wide text-faint">
                  {entry.dimension}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------

function Runner({ sessionId, onFinish }: {
  sessionId: number
  onFinish: (summary: RevisionSummary) => void
}) {
  const [question, setQuestion] = useState<ProseQuestion | null>(null)
  const [answer, setAnswer] = useState('')
  const [feedback, setFeedback] = useState<ProseFeedback | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [answered, setAnswered] = useState(0)
  const shownAt = useRef(Date.now())
  const box = useRef<HTMLTextAreaElement>(null)

  const load = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const next = await api.nextProseQuestion(sessionId)
      if (next.done) {
        onFinish(await api.finishRevision(sessionId))
        return
      }
      setQuestion(next.question ?? null)
      setAnswer('')
      setFeedback(null)
      shownAt.current = Date.now()
      window.setTimeout(() => box.current?.focus(), 0)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [sessionId, onFinish])

  useEffect(() => { void load() }, [load])

  const submit = useCallback(async () => {
    if (!question || feedback || busy || !answer.trim()) return
    setBusy(true)
    setError(null)
    try {
      setFeedback(
        await api.answerProse(sessionId, {
          item_id: question.item_id,
          answer: answer.trim(),
          response_ms: Date.now() - shownAt.current,
        }),
      )
      setAnswered((n) => n + 1)
    } catch (e) {
      // §16 — never lose a typed answer.
      setError(`${(e as Error).message} — your answer is still here.`)
    } finally {
      setBusy(false)
    }
  }, [question, feedback, busy, answer, sessionId])

  const skip = useCallback(async () => {
    if (!question || feedback || busy) return
    setBusy(true)
    try {
      setFeedback(await api.skipProse(sessionId, question.item_id))
      setAnswered((n) => n + 1)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [question, feedback, busy, sessionId])

  // §14.4 — Cmd+Enter submits.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault()
        void submit()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [submit])

  if (error && !question) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
        <p data-testid="revision-unavailable" className="rounded-lg border border-line bg-surface p-4 text-[0.875rem] text-ink">
          {error}
        </p>
        <p className="mt-2 text-[0.8125rem] text-muted">
          Quick Practice works without the network.
        </p>
      </div>
    )
  }

  if (!question) {
    return (
      <Waiting
        what="Writing a question…"
        hint="Prose questions are generated fresh each time (§16), so this is a model call."
      />
    )
  }

  return (
    <div data-testid="revision-runner" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <div className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-line-soft pb-3">
        <span className="text-[0.8125rem] tabular-nums text-muted">
          {answered + (feedback ? 0 : 1)}
        </span>
        <span className="truncate text-[0.8125rem] text-ink-soft" data-testid="revision-concept">
          {question.concept_name}
        </span>
        <span className="rounded bg-sunken px-1.5 py-0.5 text-[0.6875rem] uppercase tracking-wide text-muted">
          {question.dimension}
        </span>
        <Stopwatch />
      </div>

      <p data-testid="revision-question" className="text-[1.0625rem] leading-relaxed text-ink">
        {question.question_text}
      </p>
      <p className="mt-1 text-[0.75rem] text-faint">
        About {question.expected_length}. A hint, not a limit.
      </p>

      {!feedback ? (
        <>
          <textarea
            ref={box}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            data-testid="revision-answer"
            placeholder="Write what you remember."
            rows={8}
            className="mt-3 w-full resize-y rounded-lg border border-line bg-paper p-3 font-note text-[1rem] leading-relaxed text-ink outline-none transition placeholder:text-faint focus:border-accent focus:bg-surface"
          />
          {/* §9.6 — the skip button is as visually prominent as submit. */}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void submit()}
              disabled={busy || !answer.trim()}
              data-testid="revision-submit"
              className="flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-[0.875rem] font-medium text-white transition hover:bg-accent-deep disabled:opacity-40"
            >
              {/* Marking is a model call reading the whole answer: several
                  seconds, and the wait needs to look like work. */}
              {busy && <Spinner className="text-white" />}
              {busy ? 'Marking your answer…' : 'Submit'}
              {!busy && <kbd className="ml-1.5 text-[0.6875rem] opacity-70">⌘↵</kbd>}
            </button>
            <button
              type="button"
              onClick={() => void skip()}
              disabled={busy}
              data-testid="revision-skip"
              className="rounded-md border border-line bg-surface px-4 py-2 text-[0.875rem] font-medium text-ink transition hover:border-faint disabled:opacity-40"
            >
              Skip / I don&rsquo;t know
            </button>
          </div>
          {error && (
            <p data-testid="revision-answer-error" className="mt-2 text-[0.8125rem] text-stale">
              {error}
            </p>
          )}
        </>
      ) : (
        <Feedback
          sessionId={sessionId}
          feedback={feedback}
          onNext={() => void load()}
          onOverridden={(rating) =>
            setFeedback({ ...feedback, rating, overridden: true })
          }
        />
      )}
    </div>
  )
}

function Feedback({ sessionId, feedback, onNext, onOverridden }: {
  sessionId: number
  feedback: ProseFeedback
  onNext: () => void
  onOverridden: (rating: string) => void
}) {
  const override = useMutation({
    mutationFn: (direction: string) =>
      api.overrideProse(sessionId, feedback.attempt_id, direction),
    onSuccess: (result) => onOverridden(result.rating),
  })

  const hits = feedback.key_point_hits.filter((p) => p.hit).length

  return (
    <div data-testid="revision-feedback" data-rating={feedback.rating} className="mt-4 space-y-3">
      <div className="rounded-lg border border-line bg-surface p-3">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="text-[0.875rem] font-medium text-ink">
            {hits} of {feedback.key_point_hits.length} key points
          </span>
          <span
            data-testid="revision-rating"
            className="rounded bg-sunken px-1.5 py-0.5 text-[0.6875rem] uppercase tracking-wide text-muted"
          >
            {feedback.rating}
          </span>
        </div>
        {/* §9.6 — factual and specific, never evaluative about the person. */}
        <p className="mt-2 text-[0.875rem] leading-relaxed text-ink-soft">
          {feedback.feedback}
        </p>
      </div>

      <ul className="space-y-1" data-testid="key-points">
        {feedback.key_point_hits.map((point, i) => (
          <li
            key={i}
            data-hit={point.hit ? 'true' : 'false'}
            className="flex items-baseline gap-2 rounded-md px-2 py-1.5 text-[0.8125rem] odd:bg-paper"
          >
            <span
              className={`shrink-0 ${point.hit ? 'text-mastery-3' : 'text-faint'}`}
              aria-hidden="true"
            >
              {point.hit ? '✓' : '·'}
            </span>
            <span className={point.hit ? 'text-ink' : 'text-muted'}>{point.point}</span>
          </li>
        ))}
      </ul>

      {feedback.expected_answer && (
        <details className="rounded-lg border border-line bg-surface p-3">
          <summary className="cursor-pointer text-[0.8125rem] font-medium text-ink">
            Expected answer
          </summary>
          <p className="mt-2 text-[0.875rem] leading-relaxed text-ink-soft">
            {feedback.expected_answer}
          </p>
        </details>
      )}

      {/* §9.4 — always present, both of them. Tinted, lightly: the colour is
          there to tell the two apart at a glance, not to grade the person.
          §9.6 forbids escalation, so this is a wash and a border, never a
          filled red button. */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => override.mutate('got_it')}
          disabled={override.isPending || feedback.overridden}
          data-testid="override-got-it"
          className="rounded-md border border-emerald-600/50 bg-emerald-50/70 px-3 py-1.5 text-[0.8125rem] text-emerald-800 transition hover:border-emerald-600 hover:bg-emerald-50 disabled:opacity-40"
        >
          {override.isPending && override.variables === 'got_it'
            ? 'Saving…'
            : 'I actually got this'}
        </button>
        <button
          type="button"
          onClick={() => override.mutate('wrong')}
          disabled={override.isPending || feedback.overridden}
          data-testid="override-wrong"
          className="rounded-md border border-rose-500/50 bg-rose-50/70 px-3 py-1.5 text-[0.8125rem] text-rose-800 transition hover:border-rose-500 hover:bg-rose-50 disabled:opacity-40"
        >
          {override.isPending && override.variables === 'wrong'
            ? 'Saving…'
            : 'No, I was wrong'}
        </button>
        <button
          type="button"
          onClick={onNext}
          data-testid="revision-next"
          className="ml-auto rounded-md bg-accent px-4 py-2 text-[0.875rem] font-medium text-white transition hover:bg-accent-deep"
        >
          Next
        </button>
      </div>
    </div>
  )
}

/** §9.2 — "Show a session stopwatch, never a per-question countdown." */
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
  return (
    <span data-testid="revision-stopwatch" className="ml-auto text-[0.8125rem] tabular-nums text-faint">
      {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}
    </span>
  )
}

// --------------------------------------------------------------------------

function Summary({ sessionId, summary, onDone }: {
  sessionId: number
  summary: RevisionSummary
  onDone: () => void
}) {
  const [retest, setRetest] = useState<ProseQuestion | null>(null)
  const [retestOf, setRetestOf] = useState<number | null>(null)
  const [answer, setAnswer] = useState('')
  const [result, setResult] = useState<ProseFeedback | null>(null)

  const startRetest = useMutation({
    mutationFn: ({ attemptId, mode }: { attemptId: number; mode: string }) =>
      api.startRetest(sessionId, attemptId, mode),
    onSuccess: (q, vars) => {
      setRetest(q as unknown as ProseQuestion)
      setRetestOf(vars.attemptId)
      setResult(null)
      setAnswer('')
    },
  })

  const answerRetest = useMutation({
    mutationFn: () =>
      api.answerRetest(sessionId, {
        question_id: (retest as unknown as { question_id: number }).question_id,
        retest_of_attempt_id: retestOf!,
        answer: answer.trim(),
      }),
    onSuccess: setResult,
  })

  const minutes = Math.floor((summary.duration_ms ?? 0) / 60000)
  const seconds = Math.floor(((summary.duration_ms ?? 0) % 60000) / 1000)

  return (
    <div data-testid="revision-summary" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      {/* §9.6 — say what was done, never what was left. */}
      <h2 className="text-xl font-semibold tracking-tight text-ink">
        {summary.answered} answered
      </h2>
      <p className="mt-1 text-[0.875rem] text-muted">
        {minutes}:{String(seconds).padStart(2, '0')} of writing. That counts.
      </p>

      {summary.per_concept.length > 0 && (
        <ul className="mt-4 space-y-1" data-testid="revision-summary-concepts">
          {summary.per_concept.map((entry) => (
            <li
              key={entry.concept_id}
              className="flex items-baseline gap-2 rounded-md px-2 py-1.5 odd:bg-paper"
            >
              <span className="min-w-0 flex-1 truncate text-[0.8125rem] text-ink">
                {entry.concept_name}
              </span>
              <span className="shrink-0 text-[0.6875rem] uppercase tracking-wide text-faint">
                {entry.ratings.join(', ')}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* §9.5 — retest offers for anything rated Again or Hard. */}
      {summary.retest_offers.length > 0 && !retest && (
        <section className="mt-6" data-testid="retest-offers">
          <h3 className="text-[0.8125rem] font-semibold tracking-tight text-ink">
            Try again while it is fresh
          </h3>
          <p className="mt-1 text-[0.75rem] leading-relaxed text-muted">
            Optional, and it cannot make your schedule worse — the first answer
            is what counts.
          </p>
          <ul className="mt-2 space-y-1.5">
            {summary.retest_offers.map((offer) => (
              <li
                key={offer.attempt_id}
                className="rounded-lg border border-line bg-surface p-3"
              >
                <p className="text-[0.8125rem] text-ink">{offer.concept_name}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    data-testid={`retest-same-${offer.attempt_id}`}
                    onClick={() =>
                      startRetest.mutate({ attemptId: offer.attempt_id, mode: 'same' })
                    }
                    className="rounded-md border border-line px-2.5 py-1 text-[0.75rem] text-ink transition hover:border-accent"
                  >
                    Same question
                  </button>
                  <button
                    type="button"
                    data-testid={`retest-rephrased-${offer.attempt_id}`}
                    onClick={() =>
                      startRetest.mutate({
                        attemptId: offer.attempt_id,
                        mode: 'rephrased',
                      })
                    }
                    className="rounded-md border border-line px-2.5 py-1 text-[0.75rem] text-ink transition hover:border-accent"
                  >
                    Rephrased
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {retest && !result && (
        <section className="mt-6" data-testid="retest-runner">
          <p className="text-[1rem] leading-relaxed text-ink">
            {retest.question_text}
          </p>
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            data-testid="retest-answer"
            rows={6}
            className="mt-3 w-full resize-y rounded-lg border border-line bg-paper p-3 font-note text-[1rem] leading-relaxed text-ink outline-none focus:border-accent focus:bg-surface"
          />
          <button
            type="button"
            onClick={() => answerRetest.mutate()}
            disabled={!answer.trim() || answerRetest.isPending}
            data-testid="retest-submit"
            className="mt-2 rounded-md bg-accent px-4 py-2 text-[0.875rem] font-medium text-white transition hover:bg-accent-deep disabled:opacity-40"
          >
            {answerRetest.isPending ? 'Marking…' : 'Submit'}
          </button>
        </section>
      )}

      {result && (
        <div data-testid="retest-feedback" className="mt-6 rounded-lg border border-line bg-surface p-3">
          <p className="text-[0.875rem] leading-relaxed text-ink-soft">
            {result.feedback}
          </p>
          <p className="mt-2 text-[0.75rem] text-faint">
            Logged as a retest. Your schedule still follows the first answer.
          </p>
        </div>
      )}

      <button
        type="button"
        onClick={onDone}
        data-testid="revision-done"
        className="mt-6 rounded-md border border-line bg-surface px-4 py-2 text-[0.875rem] text-ink transition hover:border-accent"
      >
        Done
      </button>
    </div>
  )
}

function Stat({ label, value, testid }: {
  label: string
  value: React.ReactNode
  testid?: string
}) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3" data-testid={testid}>
      {/* Neutral, always. §9.6 forbids escalation here. */}
      <div className="text-xl font-semibold tabular-nums text-ink">{value}</div>
      <div className="mt-0.5 text-[0.6875rem] text-muted">{label}</div>
    </div>
  )
}
