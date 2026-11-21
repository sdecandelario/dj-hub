import type { ReactNode } from 'react'

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
  interrupted: 'warn', cancelled: '', undone: '', discarded: '', have: 'ok', maybe: 'warn', missing: 'danger', wanted: 'ok',
}

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return <Badge tone={STATUS_TONE[status]}>{label ?? status}</Badge>
}
