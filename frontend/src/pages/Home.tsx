import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { api, type Settings, type Summary } from '../api'
import { isRunning, startJob, useActiveJobs } from '../components/jobsContext'
import { Card, ErrorNote, StatusBadge } from '../components/ui'
import { JOB_LABELS, when } from '../components/format'

export default function Home() {
  const { data, error } = useQuery({ queryKey: ['summary'], queryFn: () => api.get<Summary>('/summary') })
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api.get<Settings>('/settings') })
  const jobs = useActiveJobs()
  const navigate = useNavigate()
  const empty = data && !data.library_files

  return (
    <>
      <div className="page-head">
        <div>
          <h1>DJ Hub</h1>
          <p className="muted">Playlists, downloads, loudness and the library in one place.</p>
        </div>
        <div className="row">
          <button onClick={() => startJob('review_downloads')} disabled={isRunning(jobs, 'review_downloads')}>
            Review downloads
          </button>
          <button onClick={() => startJob('spotify_refresh')} disabled={isRunning(jobs, 'spotify_refresh')}>
            Refresh playlists
          </button>
          <button onClick={() => startJob('library_scan')} disabled={isRunning(jobs, 'library_scan')}>
            Scan library
          </button>
        </div>
      </div>
      <ErrorNote error={error} />
      {settings.data?.missing_tools.length ? (
        <div className="callout danger">Missing: {settings.data.missing_tools.join(', ')}. Install with <code>brew install ffmpeg</code>.</div>
      ) : null}
      {empty && (
        <div className="callout info">
          The app is empty. Run <b>Scan library</b>, or add playlists in <Link to="/settings">Settings</Link>.
        </div>
      )}
      {data && (
        <>
          <h2>Workflow</h2>
          <div className="cards">
            <Card label="1. Missing from playlists" value={data.missing}
              hint={`${data.check} to check · ${data.waiting_downloads} download(s) waiting`}
              onClick={() => navigate('/playlists')} />
            <Card label="2. Downloads to review" value={data.review_pending}
              hint={data.review_generated ? `${data.review_decided} decided · reviewed ${data.review_generated}` : 'Not reviewed yet'}
              onClick={() => navigate('/downloads')} />
            <Card label="3. In 00 Inbox" value={data.inbox} hint="Waiting for a genre"
              onClick={() => navigate('/library?kind=inbox')} />
            <Card label="4. In 00 Rejected" value={data.rejected} hint="Final check, then Trash"
              onClick={() => navigate('/library?kind=rejected')} />
            <Card label="Library" value={data.library_files} hint={`${data.unsorted} unsorted`}
              onClick={() => navigate('/library')} />
          </div>
          <div className="grid-2">
            <div className="panel">
              <h2>Recent jobs</h2>
              <table>
                <tbody>
                  {data.recent_jobs.map(j => (
                    <tr key={j.id}>
                      <td>{JOB_LABELS[j.type] ?? j.type}<br /><small>{j.message}</small></td>
                      <td><StatusBadge status={j.status} /></td>
                      <td className="num"><small>{when(j.created_at)}</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p style={{ marginTop: 8 }}><Link to="/history">All history</Link></p>
            </div>
            <div className="panel">
              <h2>Recent file changes</h2>
              <table>
                <tbody>
                  {data.recent_batches.map(b => (
                    <tr key={b.id}>
                      <td>{b.label}</td>
                      <td><StatusBadge status={b.status} /></td>
                      <td className="num"><small>{when(b.created_at)}</small></td>
                    </tr>
                  ))}
                  {!data.recent_batches.length && <tr><td className="muted">No changes yet.</td></tr>}
                </tbody>
              </table>
              <p style={{ marginTop: 8 }}><Link to="/history">Undo a change</Link></p>
            </div>
          </div>
        </>
      )}
    </>
  )
}
