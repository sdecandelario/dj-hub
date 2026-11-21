import { useMutation, useQuery } from '@tanstack/react-query'
import { Fragment, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type PlaylistInfo, type PlaylistTrack } from '../api'
import { isActive, isRunning, startJob, useActiveJobs, useSoulseekJobs } from '../components/jobsContext'
import { ListToolbar } from '../components/ListToolbar'
import { useSelection } from '../components/useSelection'
import { DownloadPanel, DownloadSelectedButton } from '../components/SoulseekDownloads'
import { Badge, Card, Empty, ErrorNote, StatusBadge } from '../components/ui'
import { when } from '../components/format'

type Filter = 'missing' | 'maybe' | 'waiting' | 'downloading' | 'have' | 'all'

const STATUS_LABEL = { have: 'In library', maybe: 'Check', missing: 'Missing' }

const queryOf = (t: PlaylistTrack) => `${t.artists[0] ?? ''} ${t.title}`

export default function Playlists() {
  const [tab, setTab] = useState('all')
  const [filter, setFilter] = useState<Filter>('missing')
  const [search, setSearch] = useState('')
  const jobs = useActiveJobs()
  const downloads = useSoulseekJobs()
  const picked = useSelection()
  const lists = useQuery({ queryKey: ['playlists'], queryFn: () => api.get<PlaylistInfo[]>('/playlists') })
  const tracks = useQuery({
    queryKey: ['tracks', tab],
    queryFn: () => api.get<PlaylistTrack[]>(`/playlists/tracks?playlist=${tab}`),
  })
  const download = useMutation({ mutationFn: (query: string) => startJob('soulseek_download', { queries: [query] }) })

  const all = useMemo(() => tracks.data ?? [], [tracks.data])
  const downloading = (t: PlaylistTrack) => t.status !== 'have' && isActive(downloads.get(queryOf(t)))
  const counts = {
    missing: all.filter(t => t.status === 'missing').length,
    maybe: all.filter(t => t.status === 'maybe').length,
    waiting: all.filter(t => t.status !== 'have' && t.download).length,
    downloading: all.filter(downloading).length,
    have: all.filter(t => t.status === 'have').length,
    all: all.length,
  }

  const q = search.toLowerCase()
  const rows = all.filter(t => {
    const ok = {
      missing: t.status === 'missing',
      maybe: t.status === 'maybe',
      waiting: t.status !== 'have' && !!t.download,
      downloading: downloading(t),
      have: t.status === 'have',
      all: true,
    }[filter]
    return ok && `${t.artists.join(' ')} ${t.title}`.toLowerCase().includes(q)
  })

  const downloadable = rows.filter(t => t.status !== 'have')
  const ticked = downloadable.filter(t => picked.selected.has(t.spotify_id))

  const current = lists.data?.find(p => p.id === tab)

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
      {(lists.isLoading || tracks.isLoading) && <Empty>Loading…</Empty>}
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
          read {when(current.refreshed_at)}
        </p>
      )}
      <div className="cards">
        <Card label="Missing" value={counts.missing} selected={filter === 'missing'} onClick={() => setFilter('missing')} />
        <Card label="Download waiting" value={counts.waiting} hint="Found in the download folders"
          selected={filter === 'waiting'} onClick={() => setFilter('waiting')} />
        <Card label="Downloading" value={counts.downloading} hint="Queued or running on Soulseek"
          selected={filter === 'downloading'} onClick={() => setFilter('downloading')} />
        <Card label="Check" value={counts.maybe} hint="Other version or similar title" selected={filter === 'maybe'}
          onClick={() => setFilter('maybe')} />
        <Card label="In library" value={counts.have} selected={filter === 'have'} onClick={() => setFilter('have')} />
        <Card label="All" value={counts.all} selected={filter === 'all'} onClick={() => setFilter('all')} />
      </div>
      <ListToolbar search={search} onSearch={setSearch} placeholder="Search artist or title" empty={!rows.length}
        copyText={() => rows.map(t => `${t.artists.join(', ')} - ${t.title}`).join('\n')}
        csvName={`playlist-${current?.name ?? 'all'}-${filter}.csv`}
        csvRows={() => [
          ['Artist', 'Title', 'Status', 'Playlists', 'Projects', 'Local match'],
          ...rows.map(t => [t.artists.join(', '), t.title, STATUS_LABEL[t.status], t.playlists.join('; '),
            t.projects.join('; '), t.match?.relative_path ?? '']),
        ]}>
        <DownloadSelectedButton queries={ticked.map(queryOf)} onStarted={picked.clear} />
      </ListToolbar>
      <div className="panel flush list-table">
        <table>
          <thead>
            <tr>
              <th><input type="checkbox" aria-label="Select all" disabled={!downloadable.length}
                checked={!!downloadable.length && ticked.length === downloadable.length}
                onChange={e => picked.setAll(downloadable.map(t => t.spotify_id), e.target.checked)} /></th>
              <th>Artist</th><th>Title</th><th>Status</th><th>Local file or download</th>
              <th>Projects</th>{tab === 'all' && <th>Playlists</th>}<th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(t => {
              const query = queryOf(t)
              const job = downloads.get(query)
              return (
              <Fragment key={t.spotify_id}>
              <tr className={picked.selected.has(t.spotify_id) ? 'selected' : undefined}>
                <td>
                  {t.status !== 'have' && (
                    <input type="checkbox" aria-label="Select" checked={picked.selected.has(t.spotify_id)}
                      onChange={() => picked.toggle(t.spotify_id)} />
                  )}
                </td>
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
                <td className="actions">
                  {t.status !== 'have' && (
                    <button className="small" disabled={isActive(job) || download.isPending}
                      title="Search Soulseek (MP3 320) and download the best versions into the download folder. Waits if another download runs."
                      onClick={() => download.mutate(query)}>
                      Download
                    </button>
                  )}
                </td>
              </tr>
              {job && t.status !== 'have' && (
                <tr><td colSpan={tab === 'all' ? 8 : 7}><DownloadPanel job={job} query={query} /></td></tr>
              )}
              </Fragment>
              )
            })}
          </tbody>
        </table>
        {!rows.length && tracks.data && <Empty>No tracks match this filter.</Empty>}
      </div>
    </>
  )
}
