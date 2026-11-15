import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type PlaylistInfo, type PlaylistTrack } from '../api'
import { isRunning, startJob, useActiveJobs } from '../components/jobs'
import { Badge, Card, downloadCsv, Empty, ErrorNote, StatusBadge, when } from '../components/ui'

type Filter = 'missing' | 'maybe' | 'waiting' | 'downloaded' | 'have' | 'all'

const STATUS_LABEL = { have: 'In library', maybe: 'Check', missing: 'Missing' }

export default function Playlists() {
  const [tab, setTab] = useState('all')
  const [filter, setFilter] = useState<Filter>('missing')
  const [search, setSearch] = useState('')
  const jobs = useActiveJobs()
  const client = useQueryClient()
  const lists = useQuery({ queryKey: ['playlists'], queryFn: () => api.get<PlaylistInfo[]>('/playlists') })
  const tracks = useQuery({
    queryKey: ['tracks', tab],
    queryFn: () => api.get<PlaylistTrack[]>(`/playlists/tracks?playlist=${tab}`),
  })
  const mark = useMutation({
    mutationFn: ({ id, downloaded }: { id: string; downloaded: boolean }) =>
      api.put(`/playlists/marks/${id}`, { downloaded }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['tracks'] })
      client.invalidateQueries({ queryKey: ['playlists'] })
    },
  })

  const all = useMemo(() => tracks.data ?? [], [tracks.data])
  const counts = useMemo(() => ({
    missing: all.filter(t => t.status === 'missing' && !t.downloaded).length,
    maybe: all.filter(t => t.status === 'maybe').length,
    waiting: all.filter(t => t.status !== 'have' && t.download).length,
    downloaded: all.filter(t => t.status !== 'have' && t.downloaded).length,
    have: all.filter(t => t.status === 'have').length,
    all: all.length,
  }), [all])

  const q = search.toLowerCase()
  const rows = all.filter(t => {
    const ok = {
      missing: t.status === 'missing' && !t.downloaded,
      maybe: t.status === 'maybe',
      waiting: t.status !== 'have' && !!t.download,
      downloaded: t.status !== 'have' && t.downloaded,
      have: t.status === 'have',
      all: true,
    }[filter]
    return ok && `${t.artists.join(' ')} ${t.title}`.toLowerCase().includes(q)
  })

  const current = lists.data?.find(p => p.id === tab)
  const copyList = () => navigator.clipboard.writeText(rows.map(t => `${t.artists.join(', ')} - ${t.title}`).join('\n'))
  const exportCsv = () => downloadCsv(`playlist-${current?.name ?? 'all'}-${filter}.csv`, [
    ['Artist', 'Title', 'Status', 'Playlists', 'Projects', 'Local match'],
    ...rows.map(t => [t.artists.join(', '), t.title, STATUS_LABEL[t.status], t.playlists.join('; '),
      t.projects.join('; '), t.match?.relative_path ?? '']),
  ])

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Playlists</h1>
          <p className="muted">Spotify playlists compared with the library. Remixes and other versions show as <b>Check</b>.</p>
        </div>
        <button className="primary" onClick={() => startJob('spotify_refresh')} disabled={isRunning(jobs, 'spotify_refresh')}>
          {isRunning(jobs, 'spotify_refresh') ? 'Refreshing…' : 'Refresh from Spotify'}
        </button>
      </div>
      <ErrorNote error={lists.error || tracks.error} />
      {lists.data && !lists.data.length && (
        <Empty>No playlists yet. Add them in <Link to="/settings">Settings</Link>.</Empty>
      )}
      <div className="tabs">
        <button className={tab === 'all' ? 'active' : ''} onClick={() => setTab('all')}>All playlists</button>
        {lists.data?.map(p => (
          <button key={p.id} className={tab === p.id ? 'active' : ''} onClick={() => setTab(p.id)}>
            {p.name} <small>{p.counts.missing}</small>
          </button>
        ))}
      </div>
      {current && (
        <p className="muted">
          {current.owner && `${current.owner} · `}{current.counts.total} tracks · {current.project || 'No project'} ·
          read {when(current.refreshed_at)} via {current.source === 'api' ? 'Spotify API' : 'embed page'}
          {current.possibly_truncated && <Badge tone="warn">Only first 100 tracks: connect Spotify in Settings</Badge>}
        </p>
      )}
      <div className="cards">
        <Card label="Missing" value={counts.missing} selected={filter === 'missing'} onClick={() => setFilter('missing')} />
        <Card label="Download waiting" value={counts.waiting} hint="Found in the download folders"
          selected={filter === 'waiting'} onClick={() => setFilter('waiting')} />
        <Card label="Check" value={counts.maybe} hint="Other version or similar title" selected={filter === 'maybe'}
          onClick={() => setFilter('maybe')} />
        <Card label="Marked downloaded" value={counts.downloaded} selected={filter === 'downloaded'}
          onClick={() => setFilter('downloaded')} />
        <Card label="In library" value={counts.have} selected={filter === 'have'} onClick={() => setFilter('have')} />
        <Card label="All" value={counts.all} selected={filter === 'all'} onClick={() => setFilter('all')} />
      </div>
      <div className="row" style={{ marginBottom: 10 }}>
        <input className="search" placeholder="Search artist or title" value={search} onChange={e => setSearch(e.target.value)} />
        <span className="spacer" />
        <button onClick={copyList} disabled={!rows.length}>Copy list</button>
        <button onClick={exportCsv} disabled={!rows.length}>Export CSV</button>
      </div>
      <div className="panel flush table-wrap">
        <table>
          <thead>
            <tr>
              <th>Artist</th><th>Title</th><th>Status</th><th>Local file or download</th>
              <th>Projects</th>{tab === 'all' && <th>Playlists</th>}<th>Downloaded</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(t => (
              <tr key={t.spotify_id}>
                <td>{t.artists.join(', ')}</td>
                <td><a href={`https://open.spotify.com/track/${t.spotify_id}`} target="_blank" rel="noreferrer">{t.title}</a></td>
                <td><StatusBadge status={t.status} label={STATUS_LABEL[t.status]} /></td>
                <td>
                  {t.match && <small title={t.match.path}>{t.match.relative_path}{t.match.note && ` · ${t.match.note}`}</small>}
                  {t.status !== 'have' && t.download && (
                    <div><Link to={`/downloads?song=${t.download.song_key}`}><Badge tone="accent">Download waiting</Badge></Link></div>
                  )}
                </td>
                <td>{t.projects.map(p => <Badge key={p}>{p}</Badge>)}</td>
                {tab === 'all' && <td><small>{t.playlists.join(', ')}</small></td>}
                <td>
                  {t.status !== 'have' && (
                    <input type="checkbox" checked={t.downloaded} aria-label="Downloaded"
                      onChange={e => mark.mutate({ id: t.spotify_id, downloaded: e.target.checked })} />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && tracks.data && <Empty>No tracks match this filter.</Empty>}
      </div>
    </>
  )
}
