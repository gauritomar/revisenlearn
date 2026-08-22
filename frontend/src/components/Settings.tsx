import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type AppMeta } from '../lib/api'

/** Spec §14 Settings. §17 puts the backup controls and the Markdown export
 *  here.
 *
 *  Model assignments, FSRS parameters, similarity thresholds, priority weights,
 *  session defaults, interview mode, FX rate and the monthly cap all belong to
 *  settings this app cannot yet act on, so they are named as coming rather than
 *  rendered as dead controls.
 */
export function Settings({ meta }: { meta: AppMeta | undefined }) {
  const qc = useQueryClient()

  const { data: backups } = useQuery({
    queryKey: ['backups'],
    queryFn: api.backupList,
  })

  const backupNow = useMutation({
    mutationFn: api.backupNow,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['backups'] }),
  })

  const [exported, setExported] = useState<string | null>(null)
  const exportNotes = useMutation({
    mutationFn: () => api.exportMarkdown(),
    onSuccess: (result) =>
      setExported(
        `${result.file_count} note${result.file_count === 1 ? '' : 's'} → ${result.path}`,
      ),
  })

  return (
    <div data-testid="settings" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <h2 className="mb-5 text-xl font-semibold tracking-tight text-ink">Settings</h2>

      {/* --- API key (spec §17) --- */}
      <Section title="API key">
        <div className="flex flex-wrap items-center gap-2">
          <span
            data-testid="api-key-status"
            data-present={meta?.api_key.present ? 'true' : 'false'}
            className="text-[0.8125rem] text-ink"
          >
            {meta?.api_key.present ? (
              <>
                Present, from <strong className="font-medium">{meta.api_key.source}</strong>
              </>
            ) : (
              'Not configured'
            )}
          </span>
        </div>
        <p className="mt-2 text-[0.75rem] leading-relaxed text-muted">
          The key is read from the macOS Keychain, then <code>GEMINI_API_KEY</code>,
          then <code>creds/</code>. It is never stored in the database, never
          returned by this screen, and never logged.
          {meta?.api_key.source === 'creds-file' && (
            <>
              {' '}
              <span className="text-stale">
                It is currently in a file, which the spec does not allow. Move it
                with{' '}
                <code>uv run python -m revisenlearn.credentials --import-to-keychain</code>.
              </span>
            </>
          )}
        </p>
        <p className="mt-2 text-[0.75rem] leading-relaxed text-faint">
          No model is called yet. The first request goes out in Phase 5, and
          every one is logged with its prompt version, model and token counts.
        </p>
      </Section>

      {/* --- Backup (spec §17) --- */}
      <Section title="Backup">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => backupNow.mutate()}
            disabled={backupNow.isPending}
            data-testid="backup-now"
            className="rounded-md bg-accent px-3 py-1.5 text-[0.8125rem] font-medium text-white transition hover:bg-accent-deep disabled:opacity-50"
          >
            {backupNow.isPending ? 'Backing up…' : 'Back up now'}
          </button>
          <span className="text-[0.75rem] text-muted">
            {backups ? `${backups.backups.length} kept · ${formatBytes(backups.total_bytes)}` : '—'}
          </span>
        </div>

        <p className="mt-2 text-[0.75rem] leading-relaxed text-muted">
          A compacted copy is written automatically at the first launch after
          03:00 each day. Seven daily and four weekly copies are kept; the rest
          are removed.
        </p>

        {backupNow.isError && (
          <p data-testid="backup-error" className="mt-2 text-[0.8125rem] text-stale">
            {(backupNow.error as Error).message}
          </p>
        )}

        {backups && backups.backups.length > 0 && (
          <>
            <p className="mt-3 truncate font-mono text-[0.6875rem] text-faint">
              {backups.directory}
            </p>
            <ul data-testid="backup-list" className="mt-1.5 space-y-0.5">
              {backups.backups.slice(0, 12).map((b) => (
                <li
                  key={b.name}
                  className="flex items-baseline justify-between gap-2 rounded px-1.5 py-1 text-[0.75rem] odd:bg-paper"
                >
                  <span className="truncate font-mono text-ink-soft">{b.name}</span>
                  <span className="shrink-0 tabular-nums text-faint">
                    {formatBytes(b.size_bytes)}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>

      {/* --- Export (spec §17) --- */}
      <Section title="Export">
        <button
          type="button"
          onClick={() => exportNotes.mutate()}
          disabled={exportNotes.isPending}
          data-testid="export-markdown"
          className="rounded-md border border-line bg-paper px-3 py-1.5 text-[0.8125rem] text-ink transition hover:border-accent hover:text-accent-deep disabled:opacity-50"
        >
          {exportNotes.isPending ? 'Exporting…' : 'Export all notes as Markdown'}
        </button>

        <p className="mt-2 text-[0.75rem] leading-relaxed text-muted">
          One folder per Subject / Topic / Subtopic, one file per note, with
          front-matter giving the date and resource. Plain files — nothing there
          needs this app to read it.
        </p>

        {exported && (
          <p
            data-testid="export-result"
            className="mt-2 break-all font-mono text-[0.6875rem] text-mastery-3"
          >
            {exported}
          </p>
        )}
        {exportNotes.isError && (
          <p data-testid="export-error" className="mt-2 text-[0.8125rem] text-stale">
            {(exportNotes.error as Error).message}
          </p>
        )}
      </Section>

      <Section title="Still to come">
        <ul className="space-y-1 text-[0.8125rem] text-faint">
          <Coming phase={4}>Similarity thresholds</Coming>
          <Coming phase={5}>Model assignments, prompt versions</Coming>
          <Coming phase={6}>Session defaults</Coming>
          <Coming phase={7}>FSRS parameters, priority weights</Coming>
          <Coming phase={9}>FX rate, monthly cap, interview mode</Coming>
        </ul>
      </Section>
    </div>
  )
}

function Coming({ phase, children }: { phase: number; children: React.ReactNode }) {
  return (
    <li className="flex items-baseline gap-2">
      <span className="min-w-0 flex-1">{children}</span>
      <span className="shrink-0 text-[0.6875rem]">Phase {phase}</span>
    </li>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-3 rounded-lg border border-line bg-surface p-4">
      <h3 className="mb-2.5 text-[0.8125rem] font-semibold tracking-tight text-ink">
        {title}
      </h3>
      {children}
    </section>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1_048_576).toFixed(1)} MB`
}
