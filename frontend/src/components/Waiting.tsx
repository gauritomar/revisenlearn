/** A visible sign that a model call is in flight.
 *
 *  "There is a lot of loading because of API calls being made — let's add a
 *  loader so I know the call is going through."
 *
 *  Generation takes seconds, and a screen that simply sits there is
 *  indistinguishable from one that has failed. This says what is happening,
 *  and keeps moving so it is obviously alive.
 */
export function Waiting({ what, hint }: { what: string; hint?: string }) {
  return (
    <div
      data-testid="waiting"
      role="status"
      aria-live="polite"
      className="flex flex-col items-center gap-2 px-6 py-10 text-center"
    >
      <Spinner />
      <p className="text-[0.875rem] text-ink-soft">{what}</p>
      {hint && <p className="text-[0.75rem] text-faint">{hint}</p>}
    </div>
  )
}

/** The same motion inline, for a button that is mid-call. */
export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className={`size-4 animate-spin text-accent ${className ?? ''}`}
    >
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor"
              strokeOpacity="0.2" strokeWidth="2" />
      <path d="M8 2a6 6 0 0 1 6 6" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}
