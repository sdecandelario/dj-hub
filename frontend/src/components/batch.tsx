import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type ApplyResult, type Batch, type Step } from '../api'
import { BatchContext } from './batchContext'
import { basename, plural } from './format'

// Every file change goes through this dialog: preview -> Apply -> result (with Undo).

const relative = (root: string, path: string) => (path.startsWith(root + '/') ? path.slice(root.length + 1) : path)
const parent = (path: string) => path.split('/').slice(0, -1).join('/')

const VERB: Record<string, string> = {
  inbox: 'To 00 Inbox', reject: 'To 00 Rejected', trash: 'To the Trash', 'trash copy': 'Copy to the Trash',
  'move back': 'Move back', restore: 'Restore from the Trash', copy: 'Copy', move: 'Move', tags: 'Fix tags', rename: 'Rename', 'restore tags': 'Restore tags',
}

function groupSteps(root: string, steps: Step[]) {
  const groups = new Map<string, Step[]>()
  for (const step of steps.filter(s => s.action !== 'skip')) {
    const verb = VERB[step.label || step.action] ?? step.action
    const target = step.label === 'trash' ? 'Trash' : relative(root, parent(step.dest))
    const key = `${verb} → ${target}`
    groups.set(key, [...(groups.get(key) ?? []), step])
  }
  return [...groups.entries()]
}

export function BatchProvider({ children }: { children: ReactNode }) {
  const [batch, setBatch] = useState<Batch | null>(null)
  const [error, setError] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [applied, setApplied] = useState(0)
  const [result, setResult] = useState<ApplyResult | null>(null)
  const client = useQueryClient()

  const preview = useCallback(async (make: () => Promise<Batch>) => {
    setError('')
    setResult(null)
    setBusy(true)
    try {
      setBatch(await make())
    } catch (e) {
      setBatch(null)
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [])

  const plan = useCallback(
    (kind: Batch['kind'], payload: object) => preview(() => api.post<Batch>('/batches/preview', { kind, payload })), [preview])

  const close = async () => {
    if (batch && !result) await api.post(`/batches/${batch.id}/discard`).catch(() => {})
    setBatch(null)
    setError('')
    setResult(null)
  }

  const apply = async () => {
    if (!batch) return
    setBusy(true)
    setError('')
    try {
      setResult(await api.post<ApplyResult>(`/batches/${batch.id}/apply`))
      setApplied(n => n + 1)
      for (const key of ['files', 'tree', 'summary', 'downloads', 'batches', 'file', 'playlists', 'tracks']) {
        client.invalidateQueries({ queryKey: [key] })
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const undo = async () => {
    if (!result) return
    await preview(() => api.post<Batch>(`/batches/${result.id}/undo`))
  }

  const open = Boolean(batch || (error && !busy))
  const dialog = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const before = document.activeElement as HTMLElement | null
    dialog.current?.querySelector<HTMLElement>('button.primary, footer button')?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { close(); return }
      if (e.key !== 'Tab' || !dialog.current) return
      // Keep Tab inside the dialog: it gates every file change.
      const items = [...dialog.current.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input, select')]
      if (!items.length) return
      const first = items[0], last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
      else if (!dialog.current.contains(document.activeElement)) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); before?.focus?.() }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run only when the dialog opens or closes
  }, [open])

  const runnable = batch ? batch.plan.steps.filter(s => s.action !== 'skip') : []
  const skipped = batch ? batch.plan.steps.filter(s => s.action === 'skip') : []

  return (
    <BatchContext.Provider value={{ preview, plan, applied }}>
      {children}
      {(batch || (error && !busy)) && (
        <div className="overlay">
          <div className="dialog" ref={dialog} role="dialog" aria-modal="true" aria-labelledby="batch-title">
            <header>
              <h2 id="batch-title" style={{ margin: 0 }}>{result ? 'Done' : batch ? 'Check before applying' : 'Cannot plan this change'}</h2>
              <span className="spacer" />
              <button className="ghost" onClick={close} aria-label="Close">✕</button>
            </header>
            <div className="body">
              {error && <div className="callout danger">{error}</div>}
              {batch && !result && (
                <>
                  <p>
                    <b>{batch.label}</b>. {plural(runnable.length, 'file')} will change.
                    {batch.kind !== 'undo' && ' Nothing is deleted: removed files go to the Trash, and you can undo this later.'}
                  </p>
                  {batch.plan.problems.length > 0 && (
                    <div className="callout warn">
                      <b>{plural(batch.plan.problems.length, 'problem')} (these are skipped):</b>
                      <ul>{batch.plan.problems.map(p => <li key={p}>{p}</li>)}</ul>
                    </div>
                  )}
                  {batch.plan.notes.length > 0 && (
                    <div className="callout info">
                      <ul style={{ margin: 0, paddingLeft: 18 }}>{batch.plan.notes.map(n => <li key={n}>{n}</li>)}</ul>
                    </div>
                  )}
                  {groupSteps(batch.root, batch.plan.steps).map(([title, steps]) => (
                    <div className="group" key={title}>
                      <h4>{title} ({steps.length})</h4>
                      <ul>{steps.map(s => (
                        <li key={`${s.source}>${s.dest}`} title={s.source}>
                          {basename(s.source)}
                          {basename(s.dest) !== basename(s.source) && (
                            <div className="renamed" title={s.dest}>→ renamed to <b>{basename(s.dest)}</b></div>
                          )}
                          {s.tags && Object.keys(s.tags).length > 0 && (
                            <div className="renamed">
                              Tags: {Object.entries({ ...s.fill_tags, ...s.tags }).map(([k, v]) => `${k} = ${v ?? '(removed)'}`).join(' · ')}
                            </div>
                          )}
                        </li>
                      ))}</ul>
                    </div>
                  ))}
                  {skipped.length > 0 && (
                    <div className="group">
                      <h4 className="muted">Skipped ({skipped.length})</h4>
                      <ul>{skipped.map(s => <li key={`${s.source}>${s.dest}`} className="muted">{basename(s.source)}: {s.note}</li>)}</ul>
                    </div>
                  )}
                </>
              )}
              {result && (
                <div className={`callout ${result.status === 'applied' ? 'ok' : 'warn'}`}>
                  {result.status === 'applied'
                    ? `Applied ${plural(result.done, 'change')} (batch ${result.id}).`
                    : `Stopped after ${plural(result.done, 'change')}: ${result.error}`}
                  {result.warnings && result.warnings.length > 0 && (
                    <ul>{result.warnings.map(w => <li key={w}>{w}</li>)}</ul>
                  )}
                  {result.kind !== 'undo' && ' Rekordbox: drag the folder onto Playlists, or the new files into the existing playlist.'}
                </div>
              )}
            </div>
            <footer>
              {result ? (
                <>
                  {result.kind !== 'undo' && <button onClick={undo} disabled={busy}>Undo</button>}
                  <button className="primary" onClick={close}>Close</button>
                </>
              ) : (
                <>
                  <button onClick={close}>Cancel</button>
                  {batch && (
                    <button className="primary" onClick={apply} disabled={busy || !runnable.length}>
                      {busy ? 'Applying…' : `Apply ${plural(runnable.length, 'change')}`}
                    </button>
                  )}
                </>
              )}
            </footer>
          </div>
        </div>
      )}
    </BatchContext.Provider>
  )
}
