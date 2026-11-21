import { useState } from 'react'
import type { Tree } from '../../api'
import { isRunning, startJob, useActiveJobs } from '../../components/jobsContext'
import { plural } from '../../components/format'
import { folderPath, GENRES, SESSIONS } from './paths'

export function FolderTree({ tree, kind, folder, onPick }: {
  tree: Tree; kind: string; folder: string; onPick: (kind: string, folder: string) => void
}) {
  const jobs = useActiveJobs()
  // Folders ticked for analysis, as "kind/folder" keys.
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const count = (k: string, f?: string) =>
    tree.folders.filter(x => x.kind === k && (f === undefined || x.folder === f)).reduce((n, x) => n + x.count, 0)
  const toggle = (key: string) => setPicked(prev => { const next = new Set(prev); if (!next.delete(key)) next.add(key); return next })
  const absolute = (rel: string) => `${tree.root}/${rel}`.replace(/\/$/, '')
  // Several folders are a selection, never the loudness reference (only the whole library is).
  const analyze = (paths: string[]) => startJob('analyze', { paths, reference: false })
  const busy = isRunning(jobs, 'analyze')
  const item = (k: string, f: string, label: string, n: number) => {
    const key = `${k}/${f}`
    return (
      <div className="tree-row" key={key}>
        <input type="checkbox" checked={picked.has(key)} onChange={() => toggle(key)} aria-label={`Select ${label} for analysis`} />
        <button className={kind === k && folder === f ? 'active' : ''} onClick={() => onPick(k, f)}>
          <span>{label}</span><small>{n}</small>
        </button>
      </div>
    )
  }
  const group = (title: string, rel: string | null) => (
    <div className="tree-head">
      <h3>{title}</h3>
      {rel && <button className="small ghost" disabled={busy} onClick={() => analyze([absolute(rel)])}
        title={`Analyze every song in ${rel}`}>Analyze all</button>}
    </div>
  )
  const unsorted = tree.folders.filter(x => x.kind === 'unsorted')
  const chosen = [...picked].map(key => {
    const i = key.indexOf('/')
    return absolute(folderPath(key.slice(0, i), key.slice(i + 1)))
  })
  return (
    <div className="panel tree sticky" style={{ padding: 8 }}>
      {picked.size > 0 && (
        <div className="tree-selection">
          <b>{plural(picked.size, 'folder')} selected</b>
          <button className="small" disabled={busy} onClick={() => analyze(chosen)}>Analyze {picked.size}</button>
          <button className="small ghost" onClick={() => setPicked(new Set())}>Clear</button>
        </div>
      )}
      <div className="tree-row">
        <span className="tree-gap" />
        <button className={kind === '' ? 'active' : ''} onClick={() => onPick('', '')}>
          <span>Whole library</span><small>{count('inbox') + count('genre') + count('session') + count('unsorted')}</small>
        </button>
      </div>
      {group('Workflow', null)}
      {item('inbox', '', '00 Inbox', count('inbox'))}
      {item('rejected', '', '00 Rejected', count('rejected'))}
      {group('Genres', GENRES)}
      {tree.genres.map(g => item('genre', g, g, count('genre', g)))}
      {group('Sessions', SESSIONS)}
      {tree.sessions.map(s => item('session', s, s, count('session', s)))}
      {unsorted.length > 0 && group('Unsorted', null)}
      {unsorted.map(u => item('unsorted', u.folder, u.folder, u.count))}
    </div>
  )
}
