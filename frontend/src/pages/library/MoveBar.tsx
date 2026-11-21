import { useState } from 'react'
import type { LibraryFile, Tree } from '../../api'
import { useBatch } from '../../components/batchContext'
import { startJob, isRunning, useActiveJobs } from '../../components/jobsContext'
import { plural } from '../../components/format'
import { GENRES, INBOX, SESSIONS } from './paths'

// Moving to a genre or the Inbox changes where the song lives; a session holds extra copies.
const defaultAction = (to: string) => (to.startsWith(`${SESSIONS}/`) ? 'copy' : 'move')

export function MoveBar({ tree, files, onClear }: { tree: Tree; files: LibraryFile[]; onClear: () => void }) {
  const batch = useBatch()
  const jobs = useActiveJobs()
  const [to, setTo] = useState('')
  const [newSession, setNewSession] = useState('')
  const [action, setAction] = useState<'move' | 'copy'>('move')
  const target = to === 'new' ? (newSession.trim() && `${SESSIONS}/${newSession.trim()}`) : to
  const pickTarget = (value: string) => { setTo(value); if (value !== 'new') setAction(defaultAction(value)) }
  const plan = () => target && batch.plan('apply', { items: files.map(f => ({ source: f.rel_path, to: target, action })) })
  return (
    <div className="panel row" style={{ marginBottom: 10, padding: '8px 12px' }}>
      <b>{plural(files.length, 'song')} selected</b>
      <button className="small" disabled={isRunning(jobs, 'analyze')}
        onClick={() => startJob('analyze', { paths: files.map(f => f.path) })}>
        Analyze {files.length}
      </button>
      <span className="spacer" />
      <select value={action} onChange={e => setAction(e.target.value as 'move' | 'copy')}>
        <option value="move">Move</option>
        <option value="copy">Copy</option>
      </select>
      <span>to</span>
      <select value={to} onChange={e => pickTarget(e.target.value)}>
        <option value="">Choose a folder</option>
        <option value={INBOX}>{INBOX}</option>
        <optgroup label="Genres">{tree.genres.map(g => <option key={g} value={`${GENRES}/${g}`}>{g}</option>)}</optgroup>
        <optgroup label="Sessions">
          {tree.sessions.map(s => <option key={s} value={`${SESSIONS}/${s}`}>{s}</option>)}
          <option value="new">New session…</option>
        </optgroup>
      </select>
      {to === 'new' && (
        <input value={newSession} onChange={e => { setNewSession(e.target.value); setAction('copy') }}
          placeholder="Session name" autoFocus />
      )}
      <button className="small primary" disabled={!target} onClick={plan}>Preview</button>
      <button className="small ghost" onClick={onClear}>Clear</button>
    </div>
  )
}
