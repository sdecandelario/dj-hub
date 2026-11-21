import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Batch, type RekordboxReview, type RekordboxTrack } from '../api'
import { useBatch } from '../components/batchContext'
import { attempt } from '../components/errorBus'
import { downloadCsv, plural } from '../components/format'
import { Badge, Card, Empty, ErrorNote } from '../components/ui'

type Filter = 'todo' | 'missing' | 'moved' | 'check' | 'ok' | 'all'

const STATUS: Record<RekordboxTrack['status'], { label: string; tone: string; hint: string }> = {
  moved: { label: 'Moved', tone: 'ok', hint: 'dj-hub moved it: the exact new place is known.' },
  replaced: { label: 'Replaced', tone: 'info', hint: 'The old file was sent to the Trash. This looks like the file that took its place.' },
  similar: { label: 'Check', tone: 'warn', hint: 'No history for this file. Found by name: make sure it is the same song.' },
  missing: { label: 'Not found', tone: 'danger', hint: 'No trace of this song in the library.' },
  ok: { label: 'Back in place', tone: '', hint: 'The file exists at the old path again.' },
}

const FILTERS: Record<Filter, (t: RekordboxTrack) => boolean> = {
  todo: t => t.status !== 'ok',
  missing: t => t.status === 'missing',
  moved: t => t.status === 'moved',
  check: t => t.status === 'replaced' || t.status === 'similar',
  ok: t => t.status === 'ok',
  all: () => true,
}

const folderAndName = (path: string) => {
  const i = path.lastIndexOf('/')
  return [path.slice(0, i).replace(/^\/Users\/[^/]+/, '~'), path.slice(i + 1)]
}

export default function Rekordbox() {
  const [filter, setFilter] = useState<Filter>('todo')
  const [search, setSearch] = useState('')
  const [choice, setChoice] = useState<Record<string, string>>({})
  const [copied, setCopied] = useState('')
  const batch = useBatch()
  const { data, error, isLoading } = useQuery({ queryKey: ['rekordbox'], queryFn: () => api.get<RekordboxReview>('/rekordbox') })

  const tracks = data?.tracks ?? []
  const target = (t: RekordboxTrack) => choice[t.old_path] ?? t.new_path
  const count = (f: Filter) => tracks.filter(FILTERS[f]).length
  const q = search.toLowerCase()
  const shown = tracks.filter(t => FILTERS[filter](t) && `${t.title} ${t.old_path} ${t.new_rel}`.toLowerCase().includes(q))
  const copy = async (text: string, key: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(key); setTimeout(() => setCopied(''), 1500) } catch { /* clipboard blocked */ }
  }
  const relocatable = shown.filter(t => t.status !== 'ok' && target(t))
  const list = () => relocatable.map(t => `${t.old_path}\t${target(t)}`).join('\n')

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Rekordbox</h1>
          <p className="muted">
            Tracks Rekordbox could not export, read from the logs in <b>{data?.folder ?? '~/Documents/rekordbox'}</b>.
            dj-hub never changes Rekordbox: it shows where each file is now, so you can relocate it there.
          </p>
        </div>
      </div>
      <ErrorNote error={error} />
      {data && !data.logs.length && <Empty>No export logs found in {data.folder}.</Empty>}
      {data && data.logs.length > 0 && (
        <>
          <div className="callout info">
            <b>To fix it in Rekordbox:</b> show the missing files in your collection, choose <b>Relocate</b> on a track and pick the
            file under <b>Now</b>. Rekordbox then offers to relocate other missing tracks in the same folder. Tracks whose old
            path works again move to <b>Back in place</b>.
            <br /><small>Read {plural(data.logs.length, 'log')}: {data.logs.map(l => `${l.name} (${plural(l.tracks, 'track')})`).join(', ')}.</small>
          </div>
          <div className="cards">
            <Card label="To fix" value={count('todo')} selected={filter === 'todo'} onClick={() => setFilter('todo')} />
            <Card label="Moved by dj-hub" value={count('moved')} hint="Exact new place" selected={filter === 'moved'} onClick={() => setFilter('moved')} />
            <Card label="Check" value={count('check')} hint="Replaced or similar" selected={filter === 'check'} onClick={() => setFilter('check')} />
            <Card label="Not found" value={count('missing')} selected={filter === 'missing'} onClick={() => setFilter('missing')} />
            <Card label="Back in place" value={count('ok')} selected={filter === 'ok'} onClick={() => setFilter('ok')} />
          </div>
          <div className="row" style={{ marginBottom: 10 }}>
            <input className="search" placeholder="Search tracks or paths" value={search} onChange={e => setSearch(e.target.value)} />
            <span className="spacer" />
            <button disabled={!relocatable.length} onClick={() => copy(list(), 'list')}
              title="Old path and new path, tab separated">{copied === 'list' ? 'Copied' : `Copy ${relocatable.length} old → new`}</button>
            <button disabled={!shown.length} onClick={() => downloadCsv('rekordbox-missing.csv', [
              ['Track', 'Status', 'Old path', 'New path'],
              ...shown.map(t => [t.title, STATUS[t.status].label, t.old_path, t.status === 'ok' ? '' : target(t)])])}>Export CSV</button>
          </div>
          <div className="panel flush table-wrap">
            <table>
              <thead><tr><th>Track</th><th>Was</th><th>Now</th></tr></thead>
              <tbody>
                {shown.map(t => {
                  const [oldFolder, oldName] = folderAndName(t.old_path)
                  const now = target(t)
                  const picked = t.candidates.find(c => c.path === now)
                  const fileId = picked?.file_id ?? (now === t.new_path ? t.file_id : null)
                  const trashed = t.trail.filter(h => h.action === 'Sent to the Trash' && h.status === 'applied')
                  return (
                    <tr key={t.old_path}>
                      <td style={{ minWidth: 180 }}>
                        <b>{t.title}</b><br />
                        <small className="muted">{t.reason}{t.logs.length ? ` · ${t.logs.join(', ')}` : ''}</small>
                      </td>
                      <td style={{ minWidth: 240 }}>
                        <div>{oldName}</div>
                        <small className="mono muted" style={{ overflowWrap: 'anywhere' }}>{oldFolder}</small>
                      </td>
                      <td style={{ minWidth: 320 }}>
                        <Badge tone={STATUS[t.status].tone} title={STATUS[t.status].hint}>{STATUS[t.status].label}</Badge>{' '}
                        {t.trail.length > 0 && <small className="muted">
                          {t.trail.map(h => `${h.action} by change #${h.batch_id}`).join(' → ')}
                        </small>}
                        {t.status === 'ok' ? <div><small className="muted">Nothing to do.</small></div>
                          : now ? (
                            <>
                              <div style={{ overflowWrap: 'anywhere' }}>{now.includes('/DJ Tracks/') ? now.split('/DJ Tracks/')[1] : now}</div>
                              {t.candidates.length > 1 && (
                                <select value={now} onChange={e => setChoice({ ...choice, [t.old_path]: e.target.value })} aria-label="Other candidates">
                                  {t.candidates.map(c => <option key={c.path} value={c.path}>{c.rel_path}</option>)}
                                </select>
                              )}
                              <div className="row" style={{ marginTop: 4 }}>
                                <button className="small" onClick={() => copy(now, t.old_path)}>{copied === t.old_path ? 'Copied' : 'Copy path'}</button>
                                {fileId && <button className="small" onClick={() => attempt(api.post(`/files/${fileId}/reveal`))}>Show in Finder</button>}
                              </div>
                            </>
                          ) : <div><small className="muted">No trace in the library. Download it again, or restore it from the Trash.</small></div>}
                        {t.status !== 'moved' && t.status !== 'ok' && trashed.map(h => (
                          <button key={h.batch_id} className="small" style={{ marginTop: 4, marginRight: 4 }}
                            title="Preview undoing the change that sent the old file to the Trash"
                            onClick={() => batch.preview(() => api.post<Batch>(`/batches/${h.batch_id}/undo`))}>
                            Undo change #{h.batch_id}
                          </button>
                        ))}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {!shown.length && !isLoading && <Empty>Nothing here.</Empty>}
          </div>
        </>
      )}
    </>
  )
}
