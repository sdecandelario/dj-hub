import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type PlaylistInfo, type Settings, type SpotifyStatus } from '../api'
import { Badge, ErrorNote } from '../components/ui'
import { when } from '../components/format'
import { attempt } from '../components/errorBus'

const PROJECTS = ['Serge Candel', 'Juventudes Gilderianas', 'Perry Boys']

export default function SettingsPage() {
  const [params] = useSearchParams()
  const client = useQueryClient()
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api.get<Settings>('/settings') })
  const spotify = useQuery({ queryKey: ['spotify'], queryFn: () => api.get<SpotifyStatus>('/spotify/status') })
  const playlists = useQuery({ queryKey: ['playlists'], queryFn: () => api.get<PlaylistInfo[]>('/playlists') })
  const [sources, setSources] = useState<string | null>(null)
  const [newPlaylist, setNewPlaylist] = useState('')
  const [newProject, setNewProject] = useState('')
  const refresh = () => ['settings', 'playlists', 'tracks', 'summary'].forEach(k => client.invalidateQueries({ queryKey: [k] }))

  const saveSources = useMutation({
    mutationFn: () => api.put('/settings', { sources: (sources ?? '').split('\n').map(s => s.trim()).filter(Boolean) }),
    onSuccess: () => { setSources(null); refresh() },
  })
  const saveSoulseek = useMutation({
    mutationFn: (body: { soulseek_min_bitrate?: number; soulseek_candidates?: number }) => api.put('/settings', body),
    onSuccess: refresh,
  })
  const add = useMutation({
    mutationFn: () => api.post('/playlists', { value: newPlaylist, project: newProject }),
    onSuccess: () => { setNewPlaylist(''); refresh() },
  })
  const patch = (id: string, body: object) => attempt(api.patch(`/playlists/${id}`, body).then(refresh))
  const remove = (id: string) => attempt(api.del(`/playlists/${id}`).then(refresh))
  const s = settings.data

  return (
    <>
      <div className="page-head"><div><h1>Settings</h1></div></div>
      <ErrorNote error={settings.error || saveSources.error || saveSoulseek.error || add.error} />
      {params.get('spotify') === 'connected' && <div className="callout ok">Spotify is connected. Refresh the playlists to read them in full.</div>}
      <div className="grid-2">
        <div className="panel">
          <h2>Folders</h2>
          <dl className="kv">
            <dt>Library</dt><dd className="mono">{s?.root}</dd>
            <dt>Trash</dt><dd className="mono">{s?.trash}</dd>
            <dt>Database</dt><dd className="mono">{s?.db}</dd>
            <dt>Workers</dt><dd>{s?.workers} parallel ffmpeg measurements</dd>
          </dl>
          <h3>Download folders</h3>
          {s?.sources_locked ? (
            <>
              <ul>{s.sources.map(p => <li key={p} className="mono">{p}</li>)}</ul>
              <small className="muted">Set by DJ_SOURCES in the environment.</small>
            </>
          ) : (
            <>
              <textarea rows={3} style={{ width: '100%' }} className="mono" value={sources ?? s?.sources.join('\n') ?? ''}
                onChange={e => setSources(e.target.value)} />
              <div className="row" style={{ marginTop: 6 }}>
                <small className="muted">One absolute path per line.</small>
                <span className="spacer" />
                <button className="small" disabled={sources === null} onClick={() => saveSources.mutate()}>Save</button>
              </div>
            </>
          )}
          {s?.missing_tools.length ? <div className="callout danger">Missing: {s.missing_tools.join(', ')}</div> : null}
        </div>
        <div className="panel">
          <h2>Spotify</h2>
          {spotify.data && !spotify.data.keys && (
            <div className="callout warn">
              SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are not set in .env. Without them
              playlists cannot be read.
            </div>
          )}
          {spotify.data?.keys && (
            <>
              <p>{spotify.data.logged_in ? <Badge tone="ok">Connected</Badge> : <Badge tone="warn">Not connected</Badge>}</p>
              <p><a className="button" href="/api/spotify/login">{spotify.data.logged_in ? 'Connect again' : 'Connect Spotify'}</a></p>
              <small className="muted">
                Once, add this redirect URI to your app at developer.spotify.com: <code>{spotify.data.redirect_uri}</code>
              </small>
            </>
          )}
        </div>
      </div>
      <div className="panel">
        <h2>Soulseek</h2>
        <p className="muted">
          Only MP3 files are searched. Each song downloads into the first download folder (inside Soulseek);
          pick the best version on the Downloads page. The login is SOULSEEK_USERNAME and SOULSEEK_PASSWORD in .env.
        </p>
        {s && (
          <div className="row">
            <label>Minimum bitrate (kbps){' '}
              <input type="number" min={128} max={320} step={64} defaultValue={s.soulseek.min_bitrate} key={`b${s.soulseek.min_bitrate}`}
                onBlur={e => Number(e.target.value) !== s.soulseek.min_bitrate && saveSoulseek.mutate({ soulseek_min_bitrate: Number(e.target.value) })} />
            </label>
            <label>Versions per song{' '}
              <input type="number" min={1} max={50} defaultValue={s.soulseek.candidates} key={`c${s.soulseek.candidates}`}
                onBlur={e => Number(e.target.value) !== s.soulseek.candidates && saveSoulseek.mutate({ soulseek_candidates: Number(e.target.value) })} />
            </label>
          </div>
        )}
      </div>
      <div className="panel">
        <h2>Playlists</h2>
        <p className="muted">The project tag shows on each track, so you can see which DJ project a missing track is for.</p>
        <table>
          <thead><tr><th>Playlist</th><th>Project</th><th>Tracks</th><th>Read</th><th>Tracked</th><th></th></tr></thead>
          <tbody>
            {playlists.data?.map(p => (
              <tr key={p.id}>
                <td><a href={`https://open.spotify.com/playlist/${p.id}`} target="_blank" rel="noreferrer">{p.name}</a><br /><small className="mono">{p.id}</small></td>
                <td>
                  <input list="projects" defaultValue={p.project} onBlur={e => e.target.value !== p.project && patch(p.id, { project: e.target.value })} />
                </td>
                <td>{p.counts.total}</td>
                <td><small>{when(p.refreshed_at)}</small></td>
                <td><input type="checkbox" checked={p.tracked} onChange={e => patch(p.id, { tracked: e.target.checked })} /></td>
                <td><button className="small danger" onClick={() => { if (window.confirm(`Remove "${p.name || p.id}" and its tracks from the app? Spotify is not changed.`)) remove(p.id) }}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <datalist id="projects">{PROJECTS.map(p => <option key={p} value={p} />)}</datalist>
        <div className="row" style={{ marginTop: 12 }}>
          <input className="search" placeholder="Spotify playlist URL or ID" value={newPlaylist} onChange={e => setNewPlaylist(e.target.value)} />
          <input list="projects" placeholder="Project (optional)" value={newProject} onChange={e => setNewProject(e.target.value)} />
          <button className="primary" disabled={!newPlaylist} onClick={() => add.mutate()}>Add and read</button>
        </div>
      </div>
    </>
  )
}
