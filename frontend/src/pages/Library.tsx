import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type LibraryFile, type Tree } from '../api'
import { useBatch } from '../components/batchContext'
import { PlayerBar } from '../components/player'
import { usePlayer } from '../components/usePlayer'
import { startJob } from '../components/jobsContext'
import { AnalyzeButton } from '../components/AnalyzeButton'
import { PlayButton } from '../components/PlayButton'
import { Badge, Empty, ErrorNote } from '../components/ui'
import { clickableRow, num, plural } from '../components/format'
import { Detail } from './library/Detail'
import { FolderTree } from './library/FolderTree'
import { MoveBar } from './library/MoveBar'
import { GenrePicker, SessionPicker } from './library/FolderPickers'
import { folderPath, GENRES, SESSIONS } from './library/paths'

const MATCH = { file: 'same file', name: 'same artist and title', similar: 'similar artist and title' }

/** An Inbox song that is already in a genre or session folder. */
function InLibraryBadge({ copies }: { copies: NonNullable<LibraryFile['in_library']> }) {
  const first = copies[0]
  return (
    <Badge tone="warn" title={copies.map(c => `${c.rel_path} (${MATCH[c.match]}${c.integrated_lufs != null ? `, ${c.integrated_lufs.toFixed(1)} LUFS` : ''})`).join('\n')}>
      {copies.every(c => c.match === 'similar') ? 'Similar in' : 'Already in'} {first.kind === 'genre' ? first.folder : `session ${first.folder}`}
      {copies.length > 1 ? ` +${copies.length - 1}` : ''}
    </Badge>
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
  const [sessions, setSessions] = useState<Record<string, string[]>>({})
  // Inbox files that replace the copy already in a genre folder (the old copy goes to the Trash).
  const [replacing, setReplacing] = useState<Record<string, boolean>>({})
  // Inbox files not wanted (the library copy is better): they go to 00 Rejected, with no genre or session.
  const [discarding, setDiscarding] = useState<Record<string, boolean>>({})
  // Names typed with "+ New…": they exist only as choices until the batch is applied.
  const [newGenres, setNewGenres] = useState<string[]>([])
  const [newSessions, setNewSessions] = useState<string[]>([])
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
      setSessions(keep)
      setReplacing(keep)
      setDiscarding(keep)
    }
  }
  const pick = (k: string, f: string) => { setGenres({}); setSessions({}); setReplacing({}); setDiscarding({}); setEdits({}); setChecked(new Map()); setParams(k ? { kind: k, ...(f && { folder: f }) } : {}) }
  const select = (id: number | null) => {
    const next = new URLSearchParams(params)
    if (id) next.set('file', String(id)); else next.delete('file')
    setParams(next)
  }
  const path = folderPath(kind, folder)
  // A replacement goes to the genre of the copy it replaces; the rest go where the genre picker says.
  const genreCopy = (f: LibraryFile) => f.in_library?.find(c => c.kind === 'genre')
  const replaces = (f: LibraryFile) => !discarding[f.rel_path] && !!replacing[f.rel_path] && !!genreCopy(f)
  const genreOf = (f: LibraryFile) => (replaces(f) ? genreCopy(f)!.folder : genres[f.rel_path])
  const sortable = (files.data ?? []).filter(f => discarding[f.rel_path] || genreOf(f) || sessions[f.rel_path]?.length)
  const sortInbox = () => batch.plan('apply', {
    items: sortable.flatMap(f => {
      const rel = f.rel_path
      // A discarded file goes to 00 Rejected: no genre, no session copies.
      if (discarding[rel]) return [{ source: rel, to: '', action: 'move', discard: true }]
      // Unsaved name edits travel with the move, so they are not lost. The move comes first: a session copy needs a genre.
      const e = edits[rel], genre = genreOf(f)
      const edited = e && ((e.artist ?? f.artist ?? '') !== (f.artist ?? '') || (e.title ?? f.title ?? '') !== (f.title ?? ''))
      return [
        ...(genre ? [{ source: rel, to: `${GENRES}/${genre}`, action: 'move', ...(replaces(f) && { replace: true }),
          ...(edited && { artist: e.artist ?? f.artist ?? '', title: e.title ?? f.title ?? '' }) }] : []),
        ...(sessions[rel] ?? []).map(name => ({ source: rel, to: `${SESSIONS}/${name}`, action: 'copy' })),
      ]
    }) })
  const fixTags = (genre: boolean) => batch.plan('tags', { genre })
  const renames = (files.data ?? []).filter(f => edits[f.rel_path] && (
    (edits[f.rel_path].artist ?? f.artist ?? '') !== (f.artist ?? '') || (edits[f.rel_path].title ?? f.title ?? '') !== (f.title ?? '')))
  // Edits stay until the files are renamed, so cancelling the preview loses nothing.
  const saveNames = () => batch.plan('rename', {
    items: renames.map(f => ({ source: f.rel_path, artist: edits[f.rel_path].artist ?? f.artist ?? '', title: edits[f.rel_path].title ?? f.title ?? '' })) })
  // A saved rename gives the file a new path; choices made under the old path no longer count.
  const chosen = sortable.length
  const discards = sortable.filter(f => discarding[f.rel_path]).length
  const duplicates = files.data?.filter(f => f.in_library?.length).length ?? 0
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
                // Only the whole library can be the loudness reference; one folder is a selection.
                startJob('analyze', { path: `${tree.data?.root}/${path}`.replace(/\/$/, ''), reference: !kind })
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
                <button className="small primary" disabled={!chosen} onClick={sortInbox}>
                  {discards ? `Apply ${chosen}` : `Sort ${chosen || ''} song${chosen === 1 ? '' : 's'}`}
                </button>
              </>
            )}
          </div>
          {kind === 'inbox' && !!files.data?.length && (
            <p className="muted">Choose a genre and any sessions per song, then <b>Sort</b>. <b>+ New…</b> creates a folder when the batch is applied. Ask Claude (dj-library skill) for genre suggestions.</p>
          )}
          {kind === 'inbox' && duplicates > 0 && (
            <div className="callout warn">
              {plural(duplicates, 'song')} in the Inbox {duplicates === 1 ? 'is' : 'are'} already in the library (see the
              badges). Sorting does not replace anything: tick <b>Replace</b> to send the old genre copy to the Trash, or
              <b> Discard</b> to send the Inbox file to 00 Rejected.
            </div>
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
                  <th className="num">LUFS</th><th className="num">dBTP</th>{kind === 'inbox' && <><th>Genre</th><th>Sessions</th></>}
                </tr>
              </thead>
              <tbody>
                {files.data?.map(f => (
                  <tr key={f.id} {...clickableRow(() => select(f.id), selected === f.id)}>
                    <td className="check" onClick={e => e.stopPropagation()}>
                      <input type="checkbox" checked={checked.has(f.rel_path)} onChange={() => toggle(f)} aria-label={`Select ${f.title || f.name}`} />
                    </td>
                    <td onClick={e => e.stopPropagation()}>
                      <PlayButton player={player} track={{ song: String(f.id), file: f.id, title: f.title || f.name, name: f.rel_path }} />{' '}
                      <AnalyzeButton path={f.path} />
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
                        {!!f.in_library?.length && <> <InLibraryBadge copies={f.in_library} /></>}
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
                      <>
                        <td onClick={e => e.stopPropagation()}>
                          <label title="Not wanted (for example the library copy is better): move it to 00 Rejected">
                            <input type="checkbox" checked={!!discarding[f.rel_path]}
                              onChange={e => setDiscarding({ ...discarding, [f.rel_path]: e.target.checked })} /> Discard{' '}
                          </label>
                          {!discarding[f.rel_path] && genreCopy(f) && (
                            <label title={`Send ${genreCopy(f)!.rel_path} to the Trash and put this file in its place (undo restores it)`}>
                              <input type="checkbox" checked={!!replacing[f.rel_path]}
                                onChange={e => setReplacing({ ...replacing, [f.rel_path]: e.target.checked })} /> Replace{' '}
                            </label>
                          )}
                          {discarding[f.rel_path]
                            ? <small>to 00 Rejected</small>
                            : replaces(f)
                              ? <small>in {genreCopy(f)!.folder}</small>
                              : <GenrePicker value={genres[f.rel_path] ?? ''} options={[...(tree.data?.genres ?? []), ...newGenres.filter(n => !tree.data?.genres.includes(n))]}
                                onChange={g => setGenres({ ...genres, [f.rel_path]: g })}
                                onCreate={n => setNewGenres(g => (g.includes(n) ? g : [...g, n]))} />}
                        </td>
                        <td onClick={e => e.stopPropagation()}>
                          {discarding[f.rel_path]
                            ? <span className="muted">—</span>
                            : <SessionPicker value={sessions[f.rel_path] ?? []} options={[...(tree.data?.sessions ?? []), ...newSessions.filter(n => !tree.data?.sessions.includes(n))]}
                              onChange={v => setSessions({ ...sessions, [f.rel_path]: v })}
                              onCreate={n => setNewSessions(x => (x.includes(n) ? x : [...x, n]))} />}
                        </td>
                      </>
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
