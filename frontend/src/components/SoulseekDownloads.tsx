import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Job } from '../api'
import { attempt } from './errorBus'
import { isRunning, startJob, useActiveJobs } from './jobsContext'
import { basename } from './format'
import { Badge, StatusBadge } from './ui'

type Song = { found: number; files: Transfer[] }
type Transfer = { username: string; path: string; size: number; bytes?: number; speed?: number; state: string }

const mb = (n: number) => `${(n / 1e6).toFixed(1)} MB`
const TONE: Record<string, string> = { complete: 'ok', downloading: 'accent', failed: 'bad', aborted: 'bad' }

/** "Download selected": one Soulseek job (one login, parallel searches) for all the ticked songs. */
export function DownloadSelectedButton({ queries, onStarted }: { queries: string[]; onStarted: () => void }) {
  const jobs = useActiveJobs()
  const start = useMutation({
    mutationFn: () => startJob('soulseek_download', { queries }),
    onSuccess: id => { if (id) onStarted() },
  })
  return (
    <button className="primary" disabled={!queries.length || isRunning(jobs, 'soulseek_download') || start.isPending}
      title="Search Soulseek (MP3 320) for all ticked songs at once and download the best versions"
      onClick={() => start.mutate()}>
      Download selected{queries.length ? ` (${queries.length})` : ''}
    </button>
  )
}

/** Collapsible progress of one song's download, shown under the song. Open while it runs. */
export function DownloadPanel({ job, query }: { job: Job; query: string }) {
  const active = job.status === 'running' || job.status === 'queued'
  const [open, setOpen] = useState<boolean | undefined>()
  const shown = open ?? active
  const client = useQueryClient()
  const act = (call: Promise<unknown>) => attempt(call).then(() => client.invalidateQueries({ queryKey: ['jobs'] }))
  const song = ((job.summary.songs ?? {}) as Record<string, Song>)[query]
  const files = song?.files ?? []
  const nothing = !!song && !files.length && job.status === 'done'
  const batch = ((job.params.queries ?? []) as string[]).length > 1
  return (
    <div>
      <div className="row">
        <button className="small ghost" aria-expanded={shown} aria-label={shown ? 'Hide files' : 'Show files'}
          title={shown ? 'Hide files' : 'Show files'} onClick={() => setOpen(!shown)}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round" style={{ display: 'block', transition: 'transform .15s',
              transform: shown ? 'rotate(90deg)' : 'none' }}>
            <path d="M6 3l5 5-5 5" />
          </svg>
        </button>
        <b>Soulseek</b>
        <StatusBadge status={job.status} />
        {nothing
          ? <Badge tone="warn">Nothing downloaded</Badge>
          : <small className="muted">{song ? `${song.found} files found, ${files.length} ${active ? 'chosen' : 'downloaded'}` : job.message}</small>}
        {nothing && <small className="muted">Every version was queued, failed or had no free slot. Try again later.</small>}
        <span className="spacer" />
        {active ? (
          <>
            {batch && (
              <button className="small" title="Stop this song only; the others go on"
                onClick={() => act(api.post(`/jobs/${job.id}/skip`, { item: query }))}>Cancel song</button>
            )}
            <button className={`small${batch ? ' ghost' : ''}`} title={batch ? 'Cancels every song of this batch' : undefined}
              onClick={() => act(api.post(`/jobs/${job.id}/cancel`))}>{batch ? 'Cancel all' : 'Cancel'}</button>
          </>
        ) : (
          <>
            {job.status !== 'done' && (
              <button className="small" onClick={() => act(api.post(`/jobs/${job.id}/resume`))}>Resume</button>
            )}
            <button className="small ghost" title={batch ? 'Removes every song of this batch' : undefined}
              onClick={() => act(api.del(`/jobs/${job.id}`))}>Remove</button>
          </>
        )}
      </div>
      {shown && files.map(f => (
        <div key={`${f.username}${f.path}`} style={{ marginTop: 6 }}>
          <div className="row">
            <span title={f.path}>{basename(f.path.replace(/\\/g, '/'))}</span>
            <small className="muted">from {f.username}</small>
            <span className="spacer" />
            <small>
              {f.state === 'complete' ? mb(f.size) : `${mb(f.bytes ?? 0)} / ${mb(f.size)}`}
              {f.state === 'downloading' && f.speed ? ` · ${mb(f.speed)}/s` : ''}
            </small>
            <Badge tone={TONE[f.state]}>{f.state}</Badge>
          </div>
          {f.state === 'downloading' && (
            <div className="progress"><div style={{ width: `${f.size ? Math.round((100 * (f.bytes ?? 0)) / f.size) : 0}%` }} /></div>
          )}
        </div>
      ))}
    </div>
  )
}
