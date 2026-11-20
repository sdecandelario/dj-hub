import { useState } from 'react'
import type { Job } from '../api'
import { basename } from './format'
import { Badge, StatusBadge } from './ui'

type Transfer = { username: string; path: string; size: number; bytes?: number; speed?: number; state: string }

const mb = (n: number) => `${(n / 1e6).toFixed(1)} MB`
const TONE: Record<string, string> = { complete: 'ok', downloading: 'accent', failed: 'bad', aborted: 'bad' }

/** Collapsible progress of one download, shown under its song. Open while it runs. */
export function DownloadPanel({ job }: { job: Job }) {
  const active = job.status === 'running' || job.status === 'queued'
  const [open, setOpen] = useState<boolean | undefined>()
  const shown = open ?? active
  const files = (job.summary.files ?? []) as Transfer[]
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
        <small className="muted">{job.message}</small>
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
