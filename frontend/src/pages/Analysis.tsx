import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type AnalysisOverview, type Measurement } from '../api'
import { LoudnessHistogram, LoudnessScatter } from '../components/charts'
import { Badge, Card, ErrorNote, num, StatusBadge, when } from '../components/ui'

const valid = (r: Measurement) => r.status === 'OK' &&
  [r.integrated_lufs, r.true_peak_dbtp, r.loudness_range_lu].every(v => typeof v === 'number')

const median = (rows: Measurement[]) => {
  const a = rows.filter(valid).map(r => r.integrated_lufs as number).sort((x, y) => x - y)
  return a.length ? (a[Math.floor((a.length - 1) / 2)] + a[Math.floor(a.length / 2)]) / 2 : null
}

type Row = Measurement & { delta: number | null; priority: boolean; level: boolean; dynamic: boolean; notes: string }

// Same interpretation as the old loudness dashboard: comparisons, not correction instructions.
function annotate(row: Measurement, ref: number | null): Row {
  const ok = valid(row)
  const peak = row.true_peak_dbtp ?? 0
  const delta = ok && ref !== null ? (row.integrated_lufs as number) - ref : null
  const r = { ...row, delta, priority: row.status !== 'OK' || !!row.error || (ok && peak > 2),
    level: delta !== null && Math.abs(delta) > 3, dynamic: ok && (row.loudness_range_lu as number) > 10, notes: '' }
  const notes: string[] = []
  if (row.missing) notes.push('Missing at the latest check: historical measurement.')
  if (row.status !== 'OK') notes.push('Invalid measurement: check the file and analyze again.')
  if (row.error) notes.push('Decoding warning: inspect the details and listen.')
  if (ok && peak > 2) notes.push('High peak: verify with another meter and listen; if defects are audible, compare a trusted source.')
  else if (ok && peak > 0) notes.push('Positive peak: check playback headroom; this does not confirm distortion.')
  if (r.level) notes.push(`Loudness difference ${Math.abs(delta as number) > 6 ? 'very large' : 'noticeable'}: compare mixing passages; consider another master if a large trim is needed.`)
  if (r.dynamic) notes.push('Wide dynamics: listen to intros and outros.')
  if (!notes.length) notes.push('No notable flags. Audio quality has not been verified.')
  r.notes = notes.join(' ')
  return r
}

const REF_KEY = 'dj-hub:analysis-reference'

export default function Analysis() {
  const { data, error } = useQuery({ queryKey: ['analysis'], queryFn: () => api.get<AnalysisOverview>('/analysis') })
  const [view, setView] = useState<number | 'current'>('current')
  const [refId, setRefId] = useState<string>(() => { try { return localStorage.getItem(REF_KEY) ?? '' } catch { return '' } })
  const [filter, setFilter] = useState<'all' | 'priority' | 'level' | 'dynamic' | 'missing'>('all')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<{ key: keyof Row; dir: 1 | -1 }>({ key: 'integrated_lufs', dir: 1 })
  const runTracks = useQuery({
    queryKey: ['analysis', 'run', view],
    queryFn: () => api.get<Measurement[]>(`/analysis/runs/${view}`),
    enabled: view !== 'current',
  })

  const references = data?.references ?? []
  const reference = references.find(r => String(r.id) === refId) ?? references[0]
  const ref = reference?.median_lufs ?? null
  const source = view === 'current' ? data?.current ?? [] : (runTracks.data ?? []).map(r => ({ ...r, run_id: view }))
  const rows = useMemo(() => source.map(r => annotate(r, ref)), [source, ref])
  const active = rows.filter(r => !r.missing)
  const q = search.toLowerCase()
  const shown = rows
    .filter(r => `${r.filename} ${r.path}`.toLowerCase().includes(q))
    .filter(r => filter === 'all' ? !r.missing : filter === 'missing' ? r.missing : !r.missing && r[filter])
    .sort((a, b) => {
      const x = a[sort.key], y = b[sort.key]
      return sort.dir * (typeof x === 'number' && typeof y === 'number' ? x - y : String(x ?? '').localeCompare(String(y ?? '')))
    })
  const points = shown.filter(r => valid(r) && !r.missing).map(r => ({
    lufs: r.integrated_lufs as number, peak: r.true_peak_dbtp as number, label: r.filename, flag: r.priority }))
  const header = (key: keyof Row, label: string, numeric = true) => (
    <th className={`sortable${numeric ? ' num' : ''}`} onClick={() => setSort({ key, dir: sort.key === key ? (-sort.dir as 1 | -1) : 1 })}>
      {label}{sort.key === key ? (sort.dir === 1 ? ' ↑' : ' ↓') : ''}
    </th>
  )
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Loudness analysis</h1>
          <p className="muted">LUFS, true peak and loudness range for each file. Every run is kept as history. Audio files are only read. Start an analysis from the <Link to="/library">Library</Link>.</p>
        </div>
      </div>
      <ErrorNote error={error} />
      {data && !data.runs.length && (
        <div className="panel"><p className="muted">No runs yet. Select songs or a folder in the <Link to="/library">Library</Link> and click Analyze.</p></div>
      )}
      <div className="row" style={{ marginBottom: 12 }}>
        <label className="field">View
          <select value={String(view)} onChange={e => setView(e.target.value === 'current' ? 'current' : Number(e.target.value))}>
            <option value="current">Current library (latest per file)</option>
            {data?.runs.map(r => <option key={r.id} value={r.id}>{r.label} · {r.scope} · {r.files} files · {r.config.input}</option>)}
          </select>
        </label>
        <label className="field">Library reference
          <select value={reference ? String(reference.id) : ''} onChange={e => {
            setRefId(e.target.value)
            try { localStorage.setItem(REF_KEY, e.target.value) } catch { /* private window */ }
          }}>
            {!references.length && <option value="">No complete folder analysis yet</option>}
            {references.map(r => <option key={r.id} value={r.id}>{r.label} · median {num(r.median_lufs)} LUFS · {r.config.input}</option>)}
          </select>
        </label>
      </div>
      <div className="cards">
        <Card label="Files present" value={active.length} selected={filter === 'all'} onClick={() => setFilter('all')} />
        <Card label="Verify first" value={active.filter(r => r.priority).length} hint="Errors or high peaks"
          selected={filter === 'priority'} onClick={() => setFilter('priority')} />
        <Card label="Loudness difference" value={active.filter(r => r.level).length} hint="More than 3 LU from the reference"
          selected={filter === 'level'} onClick={() => setFilter('level')} />
        <Card label="Wide dynamics" value={active.filter(r => r.dynamic).length} selected={filter === 'dynamic'} onClick={() => setFilter('dynamic')} />
        <Card label="Missing files" value={rows.filter(r => r.missing).length} hint="Moved or renamed since"
          selected={filter === 'missing'} onClick={() => setFilter('missing')} />
        <Card label="Median of this view" value={`${num(median(active))}`} hint="LUFS" />
      </div>
      <div className="grid-2" style={{ marginBottom: 16 }}>
        <div className="panel"><h3>Loudness vs true peak</h3><LoudnessScatter points={points} reference={ref} /></div>
        <div className="panel"><h3>Distribution</h3><LoudnessHistogram points={points} reference={ref} /></div>
      </div>
      <div className="row" style={{ marginBottom: 10 }}>
        <input className="search" placeholder="Search files" value={search} onChange={e => setSearch(e.target.value)} />
      </div>
      <div className="panel flush table-wrap" style={{ maxHeight: 640 }}>
        <table>
          <thead>
            <tr>
              {header('filename', 'Track', false)}{header('integrated_lufs', 'LUFS')}{header('true_peak_dbtp', 'dBTP')}
              {header('loudness_range_lu', 'LRA')}{header('delta', 'Δ reference')}<th>Interpretation</th>
            </tr>
          </thead>
          <tbody>
            {shown.map(r => (
              <tr key={`${r.path}-${r.id}`}>
                <td title={r.path}>{r.filename}{r.missing && <> <Badge tone="warn">Missing</Badge></>}<br />
                  <small>{when(r.measured_at)}{r.origin === 'reused' ? ' · reused' : ''}</small></td>
                <td className="num">{num(r.integrated_lufs, 2)}</td>
                <td className="num">{num(r.true_peak_dbtp, 2)}</td>
                <td className="num">{num(r.loudness_range_lu, 1)}</td>
                <td className="num">{r.delta === null ? '—' : `${num(r.delta, 1)} LU`}</td>
                <td><small>{r.notes}</small></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel" style={{ marginTop: 16 }}>
        <h2>Runs</h2>
        <table>
          <thead><tr><th>Run</th><th>Scope</th><th className="num">Files</th><th className="num">Median</th><th>Status</th><th>Input</th></tr></thead>
          <tbody>
            {data?.runs.map(r => (
              <tr key={r.id} className="clickable" onClick={() => setView(r.id)}>
                <td>{r.label}{r.legacy && <> <Badge>imported</Badge></>}</td>
                <td>{r.scope}</td>
                <td className="num">{r.files}</td>
                <td className="num">{num(r.median_lufs)}</td>
                <td><StatusBadge status={r.complete ? 'done' : r.status} label={r.complete ? 'complete' : r.status} /></td>
                <td><small>{r.config.input}</small></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ marginTop: 12 }}>
        <small>LUFS is integrated loudness; dBTP estimates reconstructed peaks; LRA describes loudness variation. These do not
          certify audio quality, and a positive Δ means louder than the reference, not that it needs correcting.</small>
      </p>
    </>
  )
}
