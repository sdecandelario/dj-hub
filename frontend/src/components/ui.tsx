import type { ReactNode } from 'react'

export const num = (v: number | null | undefined, digits = 1) =>
  typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '—'

export const signed = (v: number | null | undefined, digits = 1) =>
  typeof v === 'number' && Number.isFinite(v) ? (v > 0 ? '+' : '') + v.toFixed(digits) : '—'

export const duration = (seconds: number | null | undefined) => {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return '—'
  const s = Math.round(seconds)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export const when = (iso: string | null | undefined) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export const plural = (n: number, word: string, many = word + 's') => `${n} ${n === 1 ? word : many}`

export const basename = (path: string) => path.split('/').pop() || path

export function Badge({ tone, children, title }: { tone?: string; children: ReactNode; title?: string }) {
  return (
    <span className={`badge ${tone ?? ''}`} title={title}>
      {children}
    </span>
  )
}

export function Card({ label, value, hint, selected, onClick }: {
  label: string; value: ReactNode; hint?: string; selected?: boolean; onClick?: () => void
}) {
  const body = (
    <>
      <small>{label}</small>
      <b>{value}</b>
      {hint && <small>{hint}</small>}
    </>
  )
  return onClick ? (
    <button className={`card${selected ? ' selected' : ''}`} onClick={onClick}>{body}</button>
  ) : (
    <div className="card">{body}</div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null
  return <div className="callout danger">{error instanceof Error ? error.message : String(error)}</div>
}

const STATUS_TONE: Record<string, string> = {
  done: 'ok', applied: 'ok', running: 'info', queued: 'info', preview: 'info', failed: 'danger', partial: 'warn',
  interrupted: 'warn', cancelled: '', undone: '', discarded: '', have: 'ok', maybe: 'warn', missing: 'danger',
}

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return <Badge tone={STATUS_TONE[status]}>{label ?? status}</Badge>
}

export const JOB_LABELS: Record<string, string> = {
  analyze: 'Loudness analysis',
  review_downloads: 'Downloads review',
  spotify_refresh: 'Spotify refresh',
  library_scan: 'Library scan',
  match_playlists: 'Playlist matching',
}

/** Download a CSV built from rows (first row = header). */
export function downloadCsv(filename: string, rows: (string | number)[][]) {
  const text = rows.map(r => r.map(c => `"${String(c ?? '').replace(/"/g, '""')}"`).join(',')).join('\n')
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
