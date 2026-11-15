import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type FileDetail, type Tree } from '../../api'
import { useBatch } from '../../components/batch'
import { attempt } from '../../components/errors'
import { HistoryChart } from '../../components/charts'
import { startJob } from '../../components/jobs'
import type { Player } from '../../components/player'
import { ErrorNote, num, StatusBadge, when } from '../../components/ui'
import { GENRES, SESSIONS } from './paths'

export function Detail({ id, tree, player, onClose }: { id: number; tree: Tree; player: Player; onClose: () => void }) {
  const batch = useBatch()
  const { data, error } = useQuery({ queryKey: ['file', id], queryFn: () => api.get<FileDetail>(`/files/${id}`) })
  const [genre, setGenre] = useState('')
  const [session, setSession] = useState('')
  if (error) return <div className="panel detail"><ErrorNote error={error} /></div>
  if (!data) return <div className="panel detail muted">Loading…</div>
  const genreCopy = data.kind === 'genre' ? data : data.copies.find(c => c.kind === 'genre')
  const plan = (items: object[]) => batch.plan('apply', { items })
  const changeGenre = () => {
    if (!genre) return
    const source = data.kind === 'inbox' || data.kind === 'genre' || data.kind === 'unsorted' ? data : genreCopy
    plan([{ source: (source ?? data).rel_path, to: `${GENRES}/${genre}`,
      action: (source ?? data).kind === 'session' ? 'copy' : 'move' }])
  }
  const addToSession = () => session && plan([{ source: (genreCopy ?? data).rel_path, to: `${SESSIONS}/${session}`, action: 'copy' }])
  const trash = () => batch.plan('remove', { paths: [data.rel_path] })
  return (
    <div className="panel detail sticky">
      <div className="row">
        <h2 style={{ margin: 0 }}>{data.title || data.name}</h2>
        <span className="spacer" />
        <button className="ghost small" onClick={onClose} aria-label="Close details">✕</button>
      </div>
      <p className="muted">{data.artist}</p>
      <div className="row" style={{ margin: '6px 0 12px' }}>
        <button className={`small${player.isPlaying(data.id) ? ' on' : ''}`}
          onClick={() => player.play({ song: String(data.id), file: data.id, title: data.title || data.name, name: data.rel_path })}>
          {player.isPlaying(data.id) ? '❚❚ Pause' : '▶ Play'}
        </button>
      </div>
      <dl className="kv">
        <dt>File</dt><dd className="mono">{data.rel_path}</dd>
        <dt>Folder</dt><dd>{data.kind} · {data.folder}</dd>
        <dt>Genre tag</dt><dd>{data.genre_tag || '—'}</dd>
        <dt>BPM tag</dt><dd>{data.bpm || '—'}</dd>
      </dl>
      <div className="row" style={{ marginBottom: 12 }}>
        <button className="small" onClick={() => attempt(api.post(`/files/${data.id}/reveal`))}>Show in Finder</button>
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
