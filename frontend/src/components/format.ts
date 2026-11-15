import type { KeyboardEvent } from 'react'

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

export const JOB_LABELS: Record<string, string> = {
  analyze: 'Loudness analysis',
  review_downloads: 'Downloads review',
  spotify_refresh: 'Spotify refresh',
  library_scan: 'Library scan',
  match_playlists: 'Playlist matching',
  discover: 'Finding new songs',
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

/** Props that make a clickable table row work with the keyboard too (Enter or Space on the row itself). */
export const clickableRow = (onActivate: () => void, selected?: boolean) => ({
  className: `clickable${selected ? ' selected' : ''}`,
  tabIndex: 0,
  'aria-selected': selected,
  onClick: onActivate,
  onKeyDown: (e: KeyboardEvent) => {
    if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onActivate() }
  },
})
