import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type LibraryFile, type Tree } from '../api'
import { useBatch } from '../components/batchContext'
import { PlayerBar } from '../components/player'
import { usePlayer } from '../components/usePlayer'
import { startJob } from '../components/jobsContext'
import { PlayButton } from '../components/PlayButton'
import { Badge, Empty, ErrorNote } from '../components/ui'
import { clickableRow, num, plural } from '../components/format'
import { Detail } from './library/Detail'
import { FolderTree } from './library/FolderTree'
import { MoveBar } from './library/MoveBar'
import { folderPath, GENRES } from './library/paths'

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
  const [seenApplied, setSeenApplied] = useState(batch.applied)
  if (seenApplied !== batch.applied) { setSeenApplied(batch.applied); setChecked(new Map()) }
  // After a rename, move or undo, drop choices for paths no longer listed so they cannot come back later.
  const [pruned, setPruned] = useState<{ data: unknown; search: string }>({ data: undefined, search })
  if (pruned.data !== files.data || pruned.search !== search) {
    setPruned({ data: files.data, search })
    if (files.data && !search) {
      const listed = new Set(files.data.map(f => f.rel_path))
      const keep = <T,>(o: Record<string, T>) => (Object.keys(o).every(k => listed.has(k)) ? o
        : Object.fromEntries(Object.entries(o).filter(([k]) => listed.has(k))))
      setEdits(keep)
      setGenres(keep)
    }
  }
  const pick = (k: string, f: string) => { setGenres({}); setEdits({}); setChecked(new Map()); setParams(k ? { kind: k, ...(f && { folder: f }) } : {}) }
  const select = (id: number | null) => {
    const next = new URLSearchParams(params)
    if (id) next.set('file', String(id)); else next.delete('file')
    setParams(next)
  }
  const path = folderPath(kind, folder)
  const sortInbox = () => batch.plan('apply', {
    items: Object.entries(genres).filter(([rel, g]) => g && files.data?.some(x => x.rel_path === rel)).map(([rel, g]) => {
      // Unsaved name edits travel with the move, so they are not lost.
      const f = files.data?.find(x => x.rel_path === rel), e = edits[rel]
      const edited = f && e && ((e.artist ?? f.artist ?? '') !== (f.artist ?? '') || (e.title ?? f.title ?? '') !== (f.title ?? ''))
      return { source: rel, to: `${GENRES}/${g}`, action: 'move',
        ...(edited && { artist: e.artist ?? f.artist ?? '', title: e.title ?? f.title ?? '' }) }
    }) })
  const fixTags = (genre: boolean) => batch.plan('tags', { genre })
  const renames = (files.data ?? []).filter(f => edits[f.rel_path] && (
    (edits[f.rel_path].artist ?? f.artist ?? '') !== (f.artist ?? '') || (edits[f.rel_path].title ?? f.title ?? '') !== (f.title ?? '')))
  // Edits stay until the files are renamed, so cancelling the preview loses nothing.
  const saveNames = () => batch.plan('rename', {
    items: renames.map(f => ({ source: f.rel_path, artist: edits[f.rel_path].artist ?? f.artist ?? '', title: edits[f.rel_path].title ?? f.title ?? '' })) })
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
              <button className="small" onClick={() => {
                if (!kind && !window.confirm('Analyze the whole library? This can take a long time. Files measured before are reused.')) return
                startJob('analyze', { path: `${tree.data?.root}/${path}`.replace(/\/$/, '') })
              }}>
                Analyze {kind ? 'folder' : 'library'}
              </button>
            )}
            {!kind && !search && (<>
              <button className="small" title="Fill missing artist and title tags from the file names" onClick={() => fixTags(false)}>Fix missing tags</button>
              <button className="small" title="Set every genre tag to its genre folder name" onClick={() => fixTags(true)}>Fix tags + genre</button>
            </>)}
            {kind === 'rejected' && !!files.data?.length && (
              <button className="small danger" onClick={() => batch.plan('remove', { paths: ['00 Rejected'] })}>
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
                    <input type="checkbox" checked={allChecked} onChange={toggleAll} title="Select all" aria-label="Select all"
                      ref={el => { if (el) el.indeterminate = listedChecked > 0 && !allChecked }} />
                  </th>
                  <th></th><th>Artist</th><th>Title</th>{!kind && <th>Folder</th>}{kind === 'rejected' && <th>Song</th>}
                  <th className="num">LUFS</th><th className="num">dBTP</th>{kind === 'inbox' && <th>Genre</th>}
                </tr>
              </thead>
              <tbody>
                {files.data?.map(f => (
                  <tr key={f.id} {...clickableRow(() => select(f.id), selected === f.id)}>
                    <td className="check" onClick={e => e.stopPropagation()}>
                      <input type="checkbox" checked={checked.has(f.rel_path)} onChange={() => toggle(f)} aria-label={`Select ${f.title || f.name}`} />
                    </td>
                    <td onClick={e => e.stopPropagation()}>
                      <PlayButton player={player} track={{ song: String(f.id), file: f.id, title: f.title || f.name, name: f.rel_path }} />
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
            {files.isLoading && <Empty>Loading…</Empty>}
            {files.data && !files.data.length && <Empty>No files here.</Empty>}
          </div>
        </div>
        {selected && tree.data && <Detail key={selected} id={selected} tree={tree.data} player={player} onClose={() => select(null)} />}
      </div>
      {player.track && <div className="bottombar"><PlayerBar player={player} /></div>}
    </>
  )
}
