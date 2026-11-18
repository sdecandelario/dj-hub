import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api, type Candidate } from '../api'
import { isRunning, startJob, useActiveJobs } from '../components/jobsContext'
import { ListToolbar } from '../components/ListToolbar'
import { Badge, Card, Empty, ErrorNote } from '../components/ui'

type Status = Candidate['status']

const LABEL: Record<Status, string> = { new: 'New', wanted: 'Wanted', dismissed: 'Dismissed' }

export default function Discover() {
  const [status, setStatus] = useState<Status>('new')
  const [genre, setGenre] = useState('')
  const [search, setSearch] = useState('')
  const jobs = useActiveJobs()
  const client = useQueryClient()
  const genres = useQuery({ queryKey: ['candidates', 'genres'], queryFn: () => api.get<string[]>('/candidates/genres') })
  const list = useQuery({ queryKey: ['candidates', 'list'], queryFn: () => api.get<Candidate[]>('/candidates') })
  const mark = useMutation({
    mutationFn: ({ ids, to }: { ids: number[]; to: Status }) => api.put('/candidates/status', { ids, status: to }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['candidates'] }),
  })
  const run = useMutation({ mutationFn: (g: string) => startJob('discover', { genre: g }) })
  const download = useMutation({ mutationFn: (c: Candidate) => startJob('soulseek_download', { query: `${c.artist} ${c.title}` }) })

  const selected = genre || genres.data?.[0] || ''

  const everything = useMemo(() => list.data ?? [], [list.data])
  const all = useMemo(() => everything.filter(c => c.genre === selected), [everything, selected])
  const q = search.toLowerCase()
  const counts = useMemo(() => ({
    new: all.filter(c => c.status === 'new').length,
    wanted: all.filter(c => c.status === 'wanted').length,
    dismissed: all.filter(c => c.status === 'dismissed').length,
  }), [all])
  const rows = all.filter(c => c.status === status && `${c.artist} ${c.title}`.toLowerCase().includes(q))
  const running = isRunning(jobs, 'discover')


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
        <div className="cards" style={{ marginBottom: 0, gridTemplateColumns: 'repeat(3, 250px)' }}>
          {(['new', 'wanted', 'dismissed'] as Status[]).map(s => (
            <Card key={s} label={LABEL[s]} value={counts[s]} selected={status === s} onClick={() => setStatus(s)}
              hint={{ new: 'Waiting for your decision', wanted: 'Download these from Soulseek',
                dismissed: 'Never suggested again' }[s]} />
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
        ]} />
      <div className="panel flush table-wrap">
        <table className="fixed">
          <colgroup>
            <col style={{ width: '16%' }} /><col style={{ width: '24%' }} /><col style={{ width: '26%' }} />
            <col /><col style={{ width: 170 }} />
          </colgroup>
          <thead>
            <tr><th>Artist</th><th>Title</th><th>Because you have</th><th>Notes</th><th className="actions">Decision</th></tr>
          </thead>
          <tbody>
            {rows.map(c => (
              <tr key={c.id}>
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
                        In {p.playlist}{p.project && ` · ${p.project}`}
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
                    <button className="small" disabled={isRunning(jobs, 'soulseek_download') || download.isPending}
                      title="Search Soulseek (MP3 320) and download the best versions into the download folder"
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
