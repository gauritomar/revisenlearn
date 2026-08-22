import { useUI } from '../store/ui'
import type { AppMeta } from '../lib/api'

/** Spec §14:
 *  [logo] Revise & Learn   Dashboard · Notes · Practice · Revision · Graph   ⌘K  Usage  Settings
 */

// Screens that do not exist until a later phase are rendered but disabled, so
// the shell shows the real shape of the app rather than a fake one.
const NAV: Array<{ label: string; phase: number }> = [
  { label: 'Dashboard', phase: 1 },
  { label: 'Notes', phase: 2 },
  { label: 'Practice', phase: 6 },
  { label: 'Revision', phase: 7 },
  { label: 'Graph', phase: 8 },
]

export function Header({ meta, view, onView }: {
  meta: AppMeta | undefined
  view: string
  onView: (v: string) => void
}) {
  const setPalette = useUI((s) => s.setPalette)
  const toggleLeft = useUI((s) => s.toggleLeft)
  const currentPhase = meta?.phase ?? 1

  return (
    <header
      data-testid="app-header"
      className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface/90 px-3 backdrop-blur-sm sm:px-4"
    >
      <button
        type="button"
        onClick={toggleLeft}
        aria-label="Toggle subject sidebar"
        data-testid="toggle-left-sidebar"
        className="grid size-8 shrink-0 place-items-center rounded-md text-muted transition hover:bg-sunken hover:text-ink"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M2 3.5h12M2 8h12M2 12.5h12" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      </button>

      <div className="flex min-w-0 items-center gap-2.5">
        <img
          src="/logo.png"
          alt="Revise &amp; Learn logo"
          data-testid="header-logo"
          width={28}
          height={28}
          className="size-7 shrink-0 rounded-md object-cover"
        />
        <h1
          data-testid="app-title"
          className="truncate text-[0.95rem] font-semibold tracking-tight text-ink"
        >
          Revise &amp; Learn
        </h1>
      </div>

      <nav className="ml-2 hidden min-w-0 items-center gap-0.5 lg:flex" aria-label="Main">
        {NAV.map((item) => {
          const available = item.phase <= currentPhase
          const active = view === item.label
          return (
            <button
              key={item.label}
              type="button"
              disabled={!available}
              onClick={() => available && onView(item.label)}
              title={available ? undefined : `Arrives in Phase ${item.phase}`}
              data-testid={`nav-${item.label.toLowerCase()}`}
              className={[
                'rounded-md px-2.5 py-1.5 text-[0.8125rem] transition',
                active ? 'bg-accent-wash font-medium text-accent-deep' : 'text-ink-soft',
                available ? 'hover:bg-sunken' : 'cursor-not-allowed text-faint',
              ].join(' ')}
            >
              {item.label}
            </button>
          )
        })}
      </nav>

      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        <button
          type="button"
          onClick={() => setPalette(true)}
          data-testid="open-command-palette"
          aria-label="Search"
          className="flex items-center gap-2 rounded-md border border-line bg-paper px-2.5 py-1.5 text-[0.8125rem] text-muted transition hover:border-faint hover:text-ink"
        >
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4" />
            <path d="M10.5 10.5 14 14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
          <kbd className="hidden font-ui text-[0.6875rem] tracking-wide sm:inline">⌘K</kbd>
        </button>

        <HeaderLink label="Usage" phase={9} currentPhase={currentPhase} />
        <HeaderLink label="Settings" phase={9} currentPhase={currentPhase} />
      </div>
    </header>
  )
}

function HeaderLink({ label, phase, currentPhase }: {
  label: string; phase: number; currentPhase: number
}) {
  const available = phase <= currentPhase
  return (
    <button
      type="button"
      disabled={!available}
      title={available ? undefined : `Arrives in Phase ${phase}`}
      className={[
        'hidden rounded-md px-2.5 py-1.5 text-[0.8125rem] transition sm:block',
        available ? 'text-ink-soft hover:bg-sunken' : 'cursor-not-allowed text-faint',
      ].join(' ')}
    >
      {label}
    </button>
  )
}
