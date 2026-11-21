import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Fragment, useMemo, useState } from 'react'
import { api, type Candidate } from '../api'
import { isActive, isRunning, startJob, useActiveJobs, useSoulseekJobs } from '../components/jobsContext'
import { ListToolbar } from '../components/ListToolbar'
import { useSelection } from '../components/useSelection'
import { DownloadPanel, DownloadSelectedButton } from '../components/SoulseekDownloads'
import { Badge, Card, Empty, ErrorNote } from '../components/ui'

type Status = Candidate['status']
/** The status cards plus "Downloading": songs of any status with a queued or running Soulseek job. */
type View = Status | 'downloading'

const ANY = '*any'
const NONE = '*none'

const LABEL: Record<View, string> = {
  new: 'New', wanted: 'Wanted', downloading: 'Downloading', dismissed: 'Dismissed', in_library: 'In library',
}

const queryOf = (c: Candidate) => `${c.artist} ${c.title}`

export default function Discover() {
  const [status, setStatus] = useState<View>('new')
  const [genre, setGenre] = useState('')
  const [search, setSearch] = useState('')
  const [playlist, setPlaylist] = useState('')   // '' all, ANY / NONE, or a playlist name
  const jobs = useActiveJobs()
  const downloads = useSoulseekJobs()
  const picked = useSelection()
  const client = useQueryClient()
  const genres = useQuery({ queryKey: ['candidates', 'genres'], queryFn: () => api.get<string[]>('/candidates/genres') })
  const list = useQuery({ queryKey: ['candidates', 'list'], queryFn: () => api.get<Candidate[]>('/candidates') })
  const mark = useMutation({
    mutationFn: ({ ids, to }: { ids: number[]; to: Status }) => api.put('/candidates/status', { ids, status: to }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['candidates'] }),
  })
  const run = useMutation({ mutationFn: (g: string) => startJob('discover', { genre: g }) })
  const download = useMutation({ mutationFn: (c: Candidate) => startJob('soulseek_download', { queries: [queryOf(c)] }) })

  const selected = genre || genres.data?.[0] || ''

  const everything = useMemo(() => list.data ?? [], [list.data])
  const all = useMemo(() => everything.filter(c => c.genre === selected), [everything, selected])
  const q = search.toLowerCase()
  const downloading = (c: Candidate) => isActive(downloads.get(queryOf(c)))
  const counts = {
    new: all.filter(c => c.status === 'new').length,
    wanted: all.filter(c => c.status === 'wanted').length,
    dismissed: all.filter(c => c.status === 'dismissed').length,
    in_library: all.filter(c => c.status === 'in_library').length,
    downloading: all.filter(downloading).length,
  }
  const inStatus = all.filter(c => status === 'downloading' ? downloading(c) : c.status === status)
  const playlistNames = [...new Set(inStatus.flatMap(c => c.in_playlists.map(p => p.playlist)))].sort()
  const filter = playlist === ANY || playlist === NONE || playlistNames.includes(playlist) ? playlist : ''
  const rows = inStatus.filter(c => `${c.artist} ${c.title}`.toLowerCase().includes(q) && ({
    '': true, [ANY]: c.in_playlists.length > 0, [NONE]: c.in_playlists.length === 0,
  }[filter] ?? c.in_playlists.some(p => p.playlist === filter)))
  const running = isRunning(jobs, 'discover')


  const downloadable = rows.filter(c => c.status !== 'in_library')
  const ticked = downloadable.filter(c => picked.selected.has(String(c.id)))

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Discover</h1>
          <p className="muted">
            New songs for a genre folder, found through Last.fm from the artists you already have there. Songs you
            own are never listed. Nothing here changes your files.
          </p>
        </div>
      </div>
      <ErrorNote error={list.error || genres.error || run.error} />
      <div className="tabs">
        {genres.data?.map(g => (
          <button key={g} className={g === selected ? 'active' : ''} onClick={() => setGenre(g)}>
            {g} <small>{everything.filter(c => c.genre === g && c.status === 'new').length}</small>
          </button>
        ))}
      </div>
      <div className="page-head">
        <div className="cards" style={{ marginBottom: 0, gridTemplateColumns: 'repeat(5, 200px)' }}>
          {(['new', 'wanted', 'downloading', 'in_library', 'dismissed'] as View[]).map(s => (
            <Card key={s} label={LABEL[s]} value={counts[s]} selected={status === s} onClick={() => setStatus(s)}
              hint={{ new: 'Waiting for your decision', wanted: 'Download these from Soulseek',
                downloading: 'Queued or running on Soulseek',
                in_library: 'Wanted, now in a genre folder', dismissed: 'Never suggested again' }[s]} />
          ))}
        </div>
        <button className="primary" disabled={!selected || running || run.isPending} onClick={() => run.mutate(selected)}>
          {running ? 'Searching…' : `Find new songs in ${selected}`}
        </button>
      </div>
      <ListToolbar search={search} onSearch={setSearch} placeholder="Search artist or title" empty={!rows.length}
        copyText={() => rows.map(c => `${c.artist} - ${c.title}`).join('\n')} csvName={`discover-${status}.csv`}
        csvRows={() => [
          ['Artist', 'Title', 'Genre folder', 'Score', 'Because', 'Already in playlists'],
          ...rows.map(c => [c.artist, c.title, c.genre, c.score, c.because.join('; '),
            c.in_playlists.map(p => p.playlist).join('; ')]),
        ]}>
        <select aria-label="Filter by playlist" value={filter} onChange={e => setPlaylist(e.target.value)}>
          <option value="">All songs</option>
          <option value={ANY}>Already in a playlist</option>
          <option value={NONE}>Not in any playlist</option>
          {playlistNames.map(n => <option key={n} value={n}>In {n}</option>)}
        </select>
        <DownloadSelectedButton queries={ticked.map(queryOf)} onStarted={picked.clear} />
      </ListToolbar>
      <div className="panel flush list-table">
        <table className="fixed">
          <colgroup>
            <col style={{ width: 36 }} /><col style={{ width: '14%' }} /><col style={{ width: '20%' }} /><col style={{ width: '24%' }} />
            <col /><col style={{ width: 250 }} />
          </colgroup>
          <thead>
            <tr>
              <th><input type="checkbox" aria-label="Select all" disabled={!downloadable.length}
                checked={!!downloadable.length && ticked.length === downloadable.length}
                onChange={e => picked.setAll(downloadable.map(c => String(c.id)), e.target.checked)} /></th>
              <th>Artist</th><th>Title</th><th>Because you have</th><th>Notes</th><th className="actions">Decision</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(c => (
              <Fragment key={c.id}>
              <tr>
                <td>
                  {c.status !== 'in_library' && (
                    <input type="checkbox" aria-label="Select" checked={picked.selected.has(String(c.id))}
                      onChange={() => picked.toggle(String(c.id))} />
                  )}
                </td>
                <td>{c.artist}</td>
                <td>
                  <a href={`https://open.spotify.com/search/${encodeURIComponent(`${c.artist} ${c.title}`)}`}
                    target="_blank" rel="noreferrer">{c.title}</a>
                </td>
                <td><small title={`Score ${c.score.toFixed(1)}`}>{c.because.join(', ')}</small></td>
                <td>
                  {c.in_playlists.map(p => (
                    <div key={p.playlist}>
                      <Badge tone="accent" title="Already in this Spotify playlist, so it is on your list">
                        {p.playlist}
                      </Badge>
                    </div>
                  ))}
                  {c.you_own > 0 && <div><small>You own {c.you_own} by this artist</small></div>}
                  {c.check && (
                    <div><Badge tone="warn" title={c.check.relative_path}>
                      Check: you may have {c.check.artist} - {c.check.title}
                    </Badge></div>
                  )}
                </td>
                <td className="actions">
                  <div className="row">
                    <button className="small" disabled={downloading(c) || download.isPending}
                      title="Search Soulseek (MP3 320) and download the best versions into the download folder. Waits if another download runs."
                      onClick={() => download.mutate(c)}>
                      Download
                    </button>
                    <button className={`small ok${c.status === 'wanted' ? ' on' : ''}`}
                      title={c.status === 'wanted' ? 'Click again to undo' : 'Add to the wanted list'}
                      onClick={() => mark.mutate({ ids: [c.id], to: c.status === 'wanted' ? 'new' : 'wanted' })}>
                      Want
                    </button>
                    <button className={`small danger${c.status === 'dismissed' ? ' on' : ''}`}
                      title={c.status === 'dismissed' ? 'Click again to undo' : 'Never suggest this again'}
                      onClick={() => mark.mutate({ ids: [c.id], to: c.status === 'dismissed' ? 'new' : 'dismissed' })}>
                      Dismiss
                    </button>
                  </div>
                </td>
              </tr>
              {downloads.get(queryOf(c)) && (
                <tr><td colSpan={6}><DownloadPanel job={downloads.get(queryOf(c))!} query={queryOf(c)} /></td></tr>
              )}
              </Fragment>
            ))}
          </tbody>
        </table>
        {!rows.length && list.data && (
          <Empty>
            {all.length ? 'Nothing here.' : 'No suggestions yet for this genre folder. Press Find new songs.'}
          </Empty>
        )}
      </div>
    </>
  )
}
