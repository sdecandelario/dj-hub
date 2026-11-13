import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, audioUrl, type Batch, type FileDetail, type LibraryFile, type Tree } from '../api'
import { useBatch } from '../components/batch'
import { HistoryChart } from '../components/charts'
import { PlayerBar, usePlayer } from '../components/player'
import { isRunning, startJob, useActiveJobs } from '../components/jobs'
import { Badge, Empty, ErrorNote, num, plural, StatusBadge, when } from '../components/ui'

const GENRES = 'Genres', SESSIONS = 'Sessions', INBOX = '00 Inbox'

// Moving to a genre or the Inbox changes where the song lives; a session holds extra copies.
const defaultAction = (to: string) => (to.startsWith(`${SESSIONS}/`) ? 'copy' : 'move')

function MoveBar({ tree, files, onClear }: { tree: Tree; files: LibraryFile[]; onClear: () => void }) {
  const batch = useBatch()
  const jobs = useActiveJobs()
  const [to, setTo] = useState('')
  const [newSession, setNewSession] = useState('')
  const [action, setAction] = useState<'move' | 'copy'>('move')
  const target = to === 'new' ? (newSession.trim() && `${SESSIONS}/${newSession.trim()}`) : to
  const pickTarget = (value: string) => { setTo(value); if (value !== 'new') setAction(defaultAction(value)) }
  const plan = () => target && batch.preview(() => api.post<Batch>('/batches/preview', {
    kind: 'apply', payload: { items: files.map(f => ({ source: f.rel_path, to: target, action })) },
  }))
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

function FolderTree({ tree, kind, folder, onPick }: {
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

function folderPath(kind: string, folder: string) {
  return { inbox: '00 Inbox', rejected: '00 Rejected', genre: `${GENRES}/${folder}`, session: `${SESSIONS}/${folder}`,
    unsorted: folder === '(root)' ? '' : folder, '': '' }[kind] ?? ''
}

function Detail({ id, tree, onClose }: { id: number; tree: Tree; onClose: () => void }) {
  const batch = useBatch()
  const { data, error } = useQuery({ queryKey: ['file', id], queryFn: () => api.get<FileDetail>(`/files/${id}`) })
  const [genre, setGenre] = useState('')
  const [session, setSession] = useState('')
  if (error) return <div className="panel detail"><ErrorNote error={error} /></div>
  if (!data) return <div className="panel detail muted">Loading…</div>
  const genreCopy = data.kind === 'genre' ? data : data.copies.find(c => c.kind === 'genre')
  const plan = (items: object[]) => batch.preview(() => api.post<Batch>('/batches/preview', { kind: 'apply', payload: { items } }))
  const changeGenre = () => {
    if (!genre) return
    const source = data.kind === 'inbox' || data.kind === 'genre' || data.kind === 'unsorted' ? data : genreCopy
    plan([{ source: (source ?? data).rel_path, to: `${GENRES}/${genre}`,
      action: (source ?? data).kind === 'session' ? 'copy' : 'move' }])
  }
  const addToSession = () => session && plan([{ source: (genreCopy ?? data).rel_path, to: `${SESSIONS}/${session}`, action: 'copy' }])
  const trash = () => batch.preview(() => api.post<Batch>('/batches/preview', { kind: 'remove', payload: { paths: [data.rel_path] } }))
  return (
    <div className="panel detail sticky">
      <div className="row">
        <h2 style={{ margin: 0 }}>{data.title || data.name}</h2>
        <span className="spacer" />
        <button className="ghost small" onClick={onClose}>✕</button>
      </div>
      <p className="muted">{data.artist}</p>
      <audio controls src={audioUrl(data.id)} style={{ width: '100%', margin: '6px 0 12px' }} preload="none" />
      <dl className="kv">
        <dt>File</dt><dd className="mono">{data.rel_path}</dd>
        <dt>Folder</dt><dd>{data.kind} · {data.folder}</dd>
        <dt>Genre tag</dt><dd>{data.genre_tag || '—'}</dd>
        <dt>BPM tag</dt><dd>{data.bpm || '—'}</dd>
      </dl>
      <div className="row" style={{ marginBottom: 12 }}>
        <button className="small" onClick={() => api.post(`/files/${data.id}/reveal`)}>Show in Finder</button>
        <button className="small" onClick={() => startJob('analyze', { path: data.path })}>Analyze</button>
        <button className="small danger" onClick={trash}>Send to Trash</button>
      </div>
      <h3>{data.kind === 'genre' ? 'Change genre' : 'Set genre'}</h3>
      <div className="row" style={{ marginBottom: 12 }}>
        <select value={genre} onChange={e => setGenre(e.target.value)}>
          <option value="">Choose a genre</option>
          {tree.genres.filter(g => g !== genreCopy?.folder).map(g => <option key={g}>{g}</option>)}
        </select>
        <button className="small" onClick={changeGenre} disabled={!genre}>Preview</button>
      </div>
      <h3>Add to session</h3>
      <div className="row" style={{ marginBottom: 12 }}>
        <input list="sessions" value={session} onChange={e => setSession(e.target.value)} placeholder="Session name" />
        <datalist id="sessions">{tree.sessions.map(s => <option key={s} value={s} />)}</datalist>
        <button className="small" onClick={addToSession} disabled={!session || !genreCopy}>Preview</button>
      </div>
      {!genreCopy && <p className="muted"><small>Give it a genre before adding it to a session.</small></p>}
      <h3>Copies ({data.copies.length + 1})</h3>
      <ul style={{ margin: '0 0 12px', paddingLeft: 18 }}>
        <li className="mono">{data.rel_path}</li>
        {data.copies.map(c => <li key={c.id} className="mono">{c.rel_path || c.path}</li>)}
      </ul>
      <h3>In playlists</h3>
      {data.playlists.length ? (
        <ul style={{ margin: '0 0 12px', paddingLeft: 18 }}>
          {data.playlists.map((p, i) => <li key={i}>{p.playlist} <StatusBadge status={p.status} /></li>)}
        </ul>
      ) : <p className="muted">Not matched to any playlist track.</p>}
      <h3>Loudness history</h3>
      <HistoryChart rows={data.history} />
      {data.history.length ? (
        <table>
          <thead><tr><th>When</th><th className="num">LUFS</th><th className="num">dBTP</th><th className="num">LRA</th></tr></thead>
          <tbody>
            {[...data.history].reverse().map(m => (
              <tr key={m.id} title={m.path}>
                <td><small>{when(m.measured_at)}{m.full ? ' · review' : ''}</small></td>
                <td className="num">{num(m.integrated_lufs, 2)}</td>
                <td className="num">{num(m.true_peak_dbtp, 2)}</td>
                <td className="num">{num(m.loudness_range_lu, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="muted">Not analyzed yet.</p>}
    </div>
  )
}

export default function Library() {
  const [params, setParams] = useSearchParams()
  const kind = params.get('kind') ?? ''
  const folder = params.get('folder') ?? ''
  const selected = Number(params.get('file')) || null
  const [search, setSearch] = useState('')
  const player = usePlayer()
  const [edits, setEdits] = useState<Record<string, { artist?: string; title?: string }>>({})
  const [genres, setGenres] = useState<Record<string, string>>({})
  // Kept as file objects so the selection survives searches that no longer list those files.
  const [checked, setChecked] = useState<Map<string, LibraryFile>>(new Map())
  const batch = useBatch()
  const tree = useQuery({ queryKey: ['tree'], queryFn: () => api.get<Tree>('/library/tree') })
  const files = useQuery({
    queryKey: ['files', kind, folder, search],
    queryFn: () => api.get<LibraryFile[]>(`/library/files?${new URLSearchParams({
      ...(kind && { kind }), ...(folder && { folder }), ...(search && { q: search }) })}`),
  })
  // An applied batch changes paths, so the selection would point at files that moved.
  useEffect(() => { setChecked(new Map()) }, [batch.applied])
  // After a rename, move or undo, drop choices for paths no longer listed so they cannot come back later.
  useEffect(() => {
    if (!files.data || search) return
    const listed = new Set(files.data.map(f => f.rel_path))
    const keep = <T,>(o: Record<string, T>) => (Object.keys(o).every(k => listed.has(k)) ? o
      : Object.fromEntries(Object.entries(o).filter(([k]) => listed.has(k))))
    setEdits(keep)
    setGenres(keep)
  }, [files.data, search])
  const pick = (k: string, f: string) => { setGenres({}); setEdits({}); setChecked(new Map()); setParams(k ? { kind: k, ...(f && { folder: f }) } : {}) }
  const select = (id: number | null) => {
    const next = new URLSearchParams(params)
    if (id) next.set('file', String(id)); else next.delete('file')
    setParams(next)
  }
  const path = folderPath(kind, folder)
  const sortInbox = () => batch.preview(() => api.post<Batch>('/batches/preview', {
    kind: 'apply',
    payload: { items: Object.entries(genres).filter(([rel, g]) => g && files.data?.some(x => x.rel_path === rel)).map(([rel, g]) => {
      // Unsaved name edits travel with the move, so they are not lost.
      const f = files.data?.find(x => x.rel_path === rel), e = edits[rel]
      const edited = f && e && ((e.artist ?? f.artist ?? '') !== (f.artist ?? '') || (e.title ?? f.title ?? '') !== (f.title ?? ''))
      return { source: rel, to: `${GENRES}/${g}`, action: 'move',
        ...(edited && { artist: e.artist ?? f.artist ?? '', title: e.title ?? f.title ?? '' }) }
    }) },
  }))
  const fixTags = (genre: boolean) => batch.preview(() => api.post<Batch>('/batches/preview', { kind: 'tags', payload: { genre } }))
  const renames = (files.data ?? []).filter(f => edits[f.rel_path] && (
    (edits[f.rel_path].artist ?? f.artist ?? '') !== (f.artist ?? '') || (edits[f.rel_path].title ?? f.title ?? '') !== (f.title ?? '')))
  const saveNames = () => batch.preview(async () => {
    // Edits stay until the files are renamed, so cancelling the preview loses nothing.
    return api.post<Batch>('/batches/preview', { kind: 'rename', payload: {
      items: renames.map(f => ({ source: f.rel_path, artist: edits[f.rel_path].artist ?? f.artist ?? '', title: edits[f.rel_path].title ?? f.title ?? '' })) } })
  })
  // A saved rename gives the file a new path; choices made under the old path no longer count.
  const chosen = Object.entries(genres).filter(([rel, g]) => g && files.data?.some(x => x.rel_path === rel)).length
  // The selection can include files hidden by the current search.
  const checkedFiles = [...checked.values()]
  const listedChecked = files.data?.filter(f => checked.has(f.rel_path)).length ?? 0
  const allChecked = !!files.data?.length && listedChecked === files.data.length
  const toggle = (f: LibraryFile) => {
    const next = new Map(checked)
    if (next.has(f.rel_path)) next.delete(f.rel_path); else next.set(f.rel_path, f)
    setChecked(next)
  }
  // Select all / none applies to the files listed now and keeps the rest of the selection.
  const toggleAll = () => {
    const next = new Map(checked)
    for (const f of files.data ?? []) { if (allChecked) next.delete(f.rel_path); else next.set(f.rel_path, f) }
    setChecked(next)
  }
  const title = kind ? (path || 'Library root') : 'Whole library'

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Library</h1>
          <p className="muted">{tree.data?.root}</p>
        </div>
        <div className="row">
          <input className="search" placeholder="Search artist, title or file" value={search} onChange={e => setSearch(e.target.value)} />
          <button onClick={() => startJob('library_scan')}>Scan again</button>
        </div>
      </div>
      <ErrorNote error={tree.error || files.error} />
      <div className="split" style={selected ? undefined : { gridTemplateColumns: '240px minmax(0, 1fr)' }}>
        {tree.data ? <FolderTree tree={tree.data} kind={kind} folder={folder} onPick={pick} /> : <div />}
        <div>
          <div className="row" style={{ marginBottom: 10 }}>
            <h2 style={{ margin: 0 }}>{title}</h2>
            <Badge>{plural(files.data?.length ?? 0, 'file')}</Badge>
            <span className="spacer" />
            {(kind || !search) && (
              <button className="small" onClick={() => startJob('analyze', { path: `${tree.data?.root}/${path}`.replace(/\/$/, '') })}>
                Analyze {kind ? 'folder' : 'library'}
              </button>
            )}
            {!kind && !search && (<>
              <button className="small" title="Fill missing artist and title tags from the file names" onClick={() => fixTags(false)}>Fix missing tags</button>
              <button className="small" title="Set every genre tag to its genre folder name" onClick={() => fixTags(true)}>Fix tags + genre</button>
            </>)}
            {kind === 'rejected' && !!files.data?.length && (
              <button className="small danger" onClick={() => batch.preview(() => api.post<Batch>('/batches/preview', { kind: 'remove', payload: { paths: ['00 Rejected'] } }))}>
                Empty 00 Rejected
              </button>
            )}
            {kind === 'inbox' && (
              <>
                <button className="small" disabled={!renames.length} onClick={saveNames}>Save {renames.length || ''} name change{renames.length === 1 ? '' : 's'}</button>
                <button className="small primary" disabled={!chosen} onClick={sortInbox}>Move {chosen || ''} to genres</button>
              </>
            )}
          </div>
          {kind === 'inbox' && !!files.data?.length && (
            <p className="muted">Choose a genre per song, then <b>Move to genres</b>. Ask Claude (dj-library skill) for genre suggestions.</p>
          )}
          {kind === 'rejected' && !!files.data?.length && (
            <p className="muted">Versions not chosen. Listen once more if in doubt, then send them to the Trash.</p>
          )}
          {tree.data && checkedFiles.length > 0 && (
            <MoveBar tree={tree.data} files={checkedFiles} onClear={() => setChecked(new Map())} />
          )}
          <div className="panel flush table-wrap">
            <table>
              <thead>
                <tr>
                  <th className="check">
                    <input type="checkbox" checked={allChecked} onChange={toggleAll} title="Select all"
                      ref={el => { if (el) el.indeterminate = listedChecked > 0 && !allChecked }} />
                  </th>
                  <th></th><th>Artist</th><th>Title</th>{!kind && <th>Folder</th>}{kind === 'rejected' && <th>Song</th>}
                  <th className="num">LUFS</th><th className="num">dBTP</th>{kind === 'inbox' && <th>Genre</th>}
                </tr>
              </thead>
              <tbody>
                {files.data?.map(f => (
                  <tr key={f.id} className={`clickable${selected === f.id ? ' selected' : ''}`} onClick={() => select(f.id)}>
                    <td className="check" onClick={e => e.stopPropagation()}>
                      <input type="checkbox" checked={checked.has(f.rel_path)} onChange={() => toggle(f)} />
                    </td>
                    <td onClick={e => e.stopPropagation()}>
                      <button className={`small${player.isPlaying(f.id) ? ' on' : ''}`} aria-label="Play"
                        onClick={() => player.play({ song: String(f.id), file: f.id, title: f.title || f.name, name: f.rel_path })}>
                        {player.isPlaying(f.id) ? '❚❚' : '▶'}
                      </button>
                    </td>
                    {kind === 'inbox' ? (<>
                      <td onClick={e => e.stopPropagation()}>
                        <input className="inline-edit" value={edits[f.rel_path]?.artist ?? f.artist ?? ''} aria-label="Artist"
                          onChange={e => setEdits({ ...edits, [f.rel_path]: { ...edits[f.rel_path], artist: e.target.value } })} />
                      </td>
                      <td title={f.rel_path} onClick={e => e.stopPropagation()}>
                        <input className="inline-edit" value={edits[f.rel_path]?.title ?? f.title ?? f.name} aria-label="Title"
                          onChange={e => setEdits({ ...edits, [f.rel_path]: { ...edits[f.rel_path], title: e.target.value } })} />
                        {f.genre_tag && <> <small className="muted">{f.genre_tag}</small></>}
                      </td>
                    </>) : (<>
                      <td>{f.artist || <span className="muted">—</span>}</td>
                      <td title={f.rel_path}>{f.title || f.name}{f.genre_tag && <> <small className="muted">{f.genre_tag}</small></>}</td>
                    </>)}
                    {!kind && <td><small>{f.kind === 'genre' || f.kind === 'session' ? f.folder : f.kind}</small></td>}
                    {kind === 'rejected' && <td><small>{f.folder}</small></td>}
                    <td className="num">{num(f.loudness?.integrated_lufs)}</td>
                    <td className="num">{num(f.loudness?.true_peak_dbtp)}</td>
                    {kind === 'inbox' && (
                      <td onClick={e => e.stopPropagation()}>
                        <select value={genres[f.rel_path] ?? ''} onChange={e => setGenres({ ...genres, [f.rel_path]: e.target.value })}>
                          <option value="">—</option>
                          {tree.data?.genres.map(g => <option key={g}>{g}</option>)}
                        </select>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {files.data && !files.data.length && <Empty>No files here.</Empty>}
          </div>
        </div>
        {selected && tree.data && <Detail id={selected} tree={tree.data} onClose={() => select(null)} />}
      </div>
      {player.track && <div className="bottombar"><PlayerBar player={player} /></div>}
    </>
  )
}
