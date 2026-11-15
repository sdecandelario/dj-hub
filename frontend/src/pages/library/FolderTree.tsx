import type { Tree } from '../../api'

export function FolderTree({ tree, kind, folder, onPick }: {
  tree: Tree; kind: string; folder: string; onPick: (kind: string, folder: string) => void
}) {
  const count = (k: string, f?: string) =>
    tree.folders.filter(x => x.kind === k && (f === undefined || x.folder === f)).reduce((n, x) => n + x.count, 0)
  const item = (k: string, f: string, label: string, n: number) => (
    <button key={`${k}/${f}`} className={kind === k && folder === f ? 'active' : ''} onClick={() => onPick(k, f)}>
      <span>{label}</span><small>{n}</small>
    </button>
  )
  const unsorted = tree.folders.filter(x => x.kind === 'unsorted')
  return (
    <div className="panel tree sticky" style={{ padding: 8 }}>
      {item('', '', 'Whole library', count('inbox') + count('genre') + count('session') + count('unsorted'))}
      <h3>Workflow</h3>
      {item('inbox', '', '00 Inbox', count('inbox'))}
      {item('rejected', '', '00 Rejected', count('rejected'))}
      <h3>Genres</h3>
      {tree.genres.map(g => item('genre', g, g, count('genre', g)))}
      <h3>Sessions</h3>
      {tree.sessions.map(s => item('session', s, s, count('session', s)))}
      {unsorted.length > 0 && <h3>Unsorted</h3>}
      {unsorted.map(u => item('unsorted', u.folder, u.folder, u.count))}
    </div>
  )
}
