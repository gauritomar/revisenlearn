import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../lib/api'
import { useUI } from '../store/ui'

/** Spec §14 — "Calendar (Apple-style month view with topic pills per day,
 *  click to open that day)".
 *
 *  Apple-style meaning: a plain 7-column grid, weeks starting Monday, quiet
 *  chrome, today marked with a filled dot rather than a heavy box, and the
 *  content of a day shown inline rather than behind a hover.
 */
const WEEKDAYS = ['M', 'T', 'W', 'T', 'F', 'S', 'S']

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate(),
  ).padStart(2, '0')}`

const monthKey = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`

export function Calendar() {
  const [cursor, setCursor] = useState(() => {
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), 1)
  })
  const openDate = useUI((s) => s.openDate)
  const activeDate = useUI((s) => s.activeDate)

  const month = monthKey(cursor)
  const { data } = useQuery({
    queryKey: ['calendar', month],
    queryFn: () => api.calendar(month),
  })

  const byDate = useMemo(() => {
    const map = new Map<string, NonNullable<typeof data>['days'][number]>()
    for (const day of data?.days ?? []) map.set(day.date, day)
    return map
  }, [data])

  // Monday-first grid, padded to whole weeks.
  const cells = useMemo(() => {
    const firstOfMonth = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
    const offset = (firstOfMonth.getDay() + 6) % 7 // Sun=0 -> Mon=0
    const start = new Date(firstOfMonth)
    start.setDate(start.getDate() - offset)

    const out: Array<{ date: Date; inMonth: boolean }> = []
    for (let i = 0; i < 42; i++) {
      const d = new Date(start)
      d.setDate(start.getDate() + i)
      out.push({ date: d, inMonth: d.getMonth() === cursor.getMonth() })
      // Stop after the last full week that still contains this month.
      if (i >= 34 && d.getMonth() !== cursor.getMonth() && (i + 1) % 7 === 0) break
    }
    return out
  }, [cursor])

  const todayISO = iso(new Date())
  const shift = (delta: number) =>
    setCursor((c) => new Date(c.getFullYear(), c.getMonth() + delta, 1))

  return (
    <div data-testid="calendar">
      <div className="mb-2 flex items-center gap-1">
        <span
          data-testid="calendar-month"
          className="text-[0.8125rem] font-medium text-ink"
        >
          {cursor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}
        </span>
        <button
          type="button"
          onClick={() => shift(-1)}
          aria-label="Previous month"
          data-testid="calendar-prev"
          className="ml-auto grid size-6 place-items-center rounded text-muted transition hover:bg-sunken hover:text-ink"
        >
          <Chevron dir="left" />
        </button>
        <button
          type="button"
          onClick={() =>
            setCursor(new Date(new Date().getFullYear(), new Date().getMonth(), 1))
          }
          data-testid="calendar-today"
          className="rounded px-2 py-0.5 text-[0.6875rem] text-muted transition hover:bg-sunken hover:text-ink"
        >
          Today
        </button>
        <button
          type="button"
          onClick={() => shift(1)}
          aria-label="Next month"
          data-testid="calendar-next"
          className="grid size-6 place-items-center rounded text-muted transition hover:bg-sunken hover:text-ink"
        >
          <Chevron dir="right" />
        </button>
      </div>

      <div className="grid grid-cols-7 gap-px">
        {WEEKDAYS.map((w, i) => (
          <div
            key={i}
            className="pb-1 text-center text-[0.625rem] font-medium uppercase tracking-wide text-faint"
          >
            {w}
          </div>
        ))}

        {cells.map(({ date, inMonth }) => {
          const key = iso(date)
          const day = byDate.get(key)
          const isToday = key === todayISO
          const isActive = key === activeDate

          return (
            <button
              key={key}
              type="button"
              disabled={!day}
              onClick={() => day && openDate(key)}
              data-testid={`calendar-day-${key}`}
              data-has-notes={day ? 'true' : 'false'}
              title={day ? `${day.note_count} note${day.note_count === 1 ? '' : 's'}` : undefined}
              className={[
                'flex min-h-[3.1rem] flex-col items-stretch gap-0.5 rounded-md p-1 text-left transition',
                inMonth ? '' : 'opacity-35',
                day ? 'hover:bg-sunken' : 'cursor-default',
                isActive ? 'bg-accent-wash ring-1 ring-accent' : '',
              ].join(' ')}
            >
              <span
                className={[
                  'text-[0.6875rem] tabular-nums',
                  isToday ? 'font-semibold text-accent-deep' : 'text-muted',
                ].join(' ')}
              >
                {date.getDate()}
                {isToday && (
                  <span
                    className="ml-0.5 inline-block size-1 rounded-full bg-accent align-middle"
                    aria-hidden="true"
                  />
                )}
              </span>

              {/* Topic pills. Two fit legibly at 500px; the rest are counted. */}
              <span className="flex flex-col gap-0.5 overflow-hidden">
                {day?.topics.slice(0, 2).map((t) => (
                  <span
                    key={t.topic_id}
                    data-testid="calendar-pill"
                    className="truncate rounded-sm px-1 text-[0.5625rem] leading-[1.35]"
                    style={{
                      background: `${t.colour ?? '#A9A198'}22`,
                      color: t.colour ?? 'var(--color-muted)',
                    }}
                  >
                    {t.name}
                  </span>
                ))}
                {day && day.topics.length > 2 && (
                  <span className="px-1 text-[0.5625rem] leading-[1.35] text-faint">
                    +{day.topics.length - 2}
                  </span>
                )}
                {day && day.topics.length === 0 && (
                  <span className="px-1 text-[0.5625rem] leading-[1.35] text-faint">
                    {day.note_count} note{day.note_count === 1 ? '' : 's'}
                  </span>
                )}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function Chevron({ dir }: { dir: 'left' | 'right' }) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
      <path
        d={dir === 'left' ? 'm6.5 2-3.5 3 3.5 3' : 'm3.5 2 3.5 3-3.5 3'}
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** The "click to open that day" destination. */
export function DayView({ date }: { date: string }) {
  const clearActive = useUI((s) => s.clearActive)
  const openNote = useUI((s) => s.openNote)
  const openResource = useUI((s) => s.openResource)

  const { data: notes = [], isLoading } = useQuery({
    queryKey: ['notes-by-date', date],
    queryFn: () => api.notesByDate(date),
  })

  const [y, m, d] = date.split('-').map(Number)
  const label = new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  })

  return (
    <div data-testid="day-view" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <button
        type="button"
        onClick={clearActive}
        className="mb-2 flex items-center gap-1 text-[0.75rem] text-muted transition hover:text-ink"
      >
        <span aria-hidden="true">&larr;</span> Dashboard
      </button>
      <h2 className="text-xl font-semibold tracking-tight text-ink">{label}</h2>

      <div className="mt-4">
        {isLoading ? (
          <p className="text-[0.8125rem] text-faint">Loading…</p>
        ) : notes.length === 0 ? (
          <p className="text-[0.8125rem] text-faint">Nothing written on this day.</p>
        ) : (
          <ul className="space-y-1.5">
            {notes.map((note) => (
              <li key={note.id}>
                <button
                  type="button"
                  data-testid={`day-note-${note.id}`}
                  onClick={() =>
                    note.resource_id
                      ? openResource(note.resource_id)
                      // The day lists notes, so a click opens that note —
                      // not the page it happens to sit under, which may hold
                      // a different one.
                      : openNote(note.id)
                  }
                  className="w-full rounded-lg border border-line bg-surface p-3 text-left transition hover:border-faint"
                >
                  <div className="flex items-baseline gap-2">
                    <span className="min-w-0 flex-1 truncate text-[0.875rem] font-medium text-ink">
                      {note.title}
                    </span>
                    <span className="shrink-0 text-[0.6875rem] tabular-nums text-faint">
                      {note.blocks.length} {note.blocks.length === 1 ? 'block' : 'blocks'}
                    </span>
                  </div>
                  {note.blocks[0] && (
                    <p className="mt-1 truncate text-[0.75rem] text-muted">
                      {note.blocks[0].text}
                    </p>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}


/** Consolidated addendum §7 — the app's landing view.
 *
 *  The month grid on its own page rather than as a dashboard card, since it is
 *  now the first thing seen. Clicking a day opens that day (§14 of the main
 *  spec), exactly as it does from the Dashboard.
 */
export function CalendarScreen() {
  return (
    <div data-testid="calendar-screen" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <h2 className="text-xl font-semibold tracking-tight text-ink">Calendar</h2>
      <p className="mt-1 text-[0.875rem] leading-relaxed text-muted">
        What you wrote, and when. Click a day to open it.
      </p>
      <div className="mt-5 rounded-lg border border-line bg-surface p-4">
        <Calendar />
      </div>
    </div>
  )
}
