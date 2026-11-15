import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type AnalysisOverview, type Measurement } from '../api'
import { LoudnessHistogram, LoudnessScatter } from '../components/charts'
import { Badge, Card, ErrorNote, num, signed, StatusBadge, when } from '../components/ui'
import { contextFor, isValid, judge, median, order, type Level, type Verdict } from '../verdict'

type Row = Measurement & { delta: number | null; verdict: Verdict }

const TONE = { fix: 'danger', check: 'warn', ok: 'ok' } as const
const LABEL = { fix: 'Fix', check: 'Check', ok: 'OK' } as const

const REF_KEY = 'dj-hub:analysis-reference'

export default function Analysis() {
  const { data, error } = useQuery({ queryKey: ['analysis'], queryFn: () => api.get<AnalysisOverview>('/analysis') })
  const [view, setView] = useState<number | 'current'>('current')
  const [refId, setRefId] = useState<string>(() => { try { return localStorage.getItem(REF_KEY) ?? '' } catch { return '' } })
  const [filter, setFilter] = useState<'all' | Level | 'missing'>('all')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<{ key: keyof Row | 'verdict'; dir: 1 | -1 }>({ key: 'verdict', dir: -1 })
  const runTracks = useQuery({
    queryKey: ['analysis', 'run', view],
    queryFn: () => api.get<Measurement[]>(`/analysis/runs/${view}`),
    enabled: view !== 'current',
  })

  const references = data?.references ?? []
  const reference = references.find(r => String(r.id) === refId) ?? references[0]
  const ref = reference?.median_lufs ?? null
  const source = useMemo(
    () => view === 'current' ? data?.current ?? [] : (runTracks.data ?? []).map(r => ({ ...r, run_id: view })),
    [view, data, runTracks.data])
  const rows: Row[] = useMemo(() => {
    const ctx = contextFor(source.filter(r => !r.missing), ref)
    return source.map(r => ({ ...r, delta: isValid(r) && ref !== null ? (r.integrated_lufs as number) - ref : null, verdict: judge(r, ctx) }))
  }, [source, ref])
  const active = useMemo(() => rows.filter(r => !r.missing), [rows])
  const count = (level: Level) => active.filter(r => r.verdict.level === level).length
  const q = search.toLowerCase()
  const sortValue = (r: Row) => sort.key === 'verdict' ? order(r.verdict) * 100 + Math.abs(r.delta ?? 0) : r[sort.key]
  const shown = rows
    .filter(r => `${r.filename} ${r.path}`.toLowerCase().includes(q))
    .filter(r => filter === 'all' ? !r.missing : filter === 'missing' ? r.missing : !r.missing && r.verdict.level === filter)
    .sort((a, b) => {
      const x = sortValue(a), y = sortValue(b)
      return sort.dir * (typeof x === 'number' && typeof y === 'number' ? x - y : String(x ?? '').localeCompare(String(y ?? '')))
    })
  const points = shown.filter(r => isValid(r) && !r.missing).map(r => ({
    lufs: r.integrated_lufs as number, peak: r.true_peak_dbtp as number, label: r.filename, flag: r.verdict.level !== 'ok' }))
  const folders = useMemo(() => {
    const groups = new Map<string, { fix: number; check: number; ok: number }>()
    for (const r of active) {
      const dir = r.path.slice(0, r.path.lastIndexOf('/'))
      const g = groups.get(dir) ?? { fix: 0, check: 0, ok: 0 }
      g[r.verdict.level]++
      groups.set(dir, g)
    }
    return [...groups].map(([dir, g]) => ({ dir, ...g, total: g.fix + g.check + g.ok }))
      .filter(g => g.fix + g.check > 0).sort((a, b) => (b.fix * 2 + b.check) / b.total - (a.fix * 2 + a.check) / a.total).slice(0, 8)
  }, [active])
  const header = (key: keyof Row | 'verdict', label: string, numeric = true) => (
    <th className={`sortable${numeric ? ' num' : ''}`} onClick={() => setSort({ key, dir: sort.key === key ? (-sort.dir as 1 | -1) : key === 'verdict' ? -1 : 1 })}>
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
        <Card label="Fix" value={count('fix')} hint="Replace or find another version"
          selected={filter === 'fix'} onClick={() => setFilter('fix')} />
        <Card label="Check" value={count('check')} hint="Listen or set the gain"
          selected={filter === 'check'} onClick={() => setFilter('check')} />
        <Card label="OK" value={count('ok')} hint="Nothing to do"
          selected={filter === 'ok'} onClick={() => setFilter('ok')} />
        <Card label="Missing files" value={rows.filter(r => r.missing).length} hint="Moved or renamed since"
          selected={filter === 'missing'} onClick={() => setFilter('missing')} />
        <Card label="Median of this view" value={`${num(median(active.filter(isValid).map(r => r.integrated_lufs as number)))}`} hint="LUFS" />
      </div>
      {active.length > 0 && !active.some(r => typeof r.tone_air_db === 'number') && (
        <div className="callout">These results predate the loud-section and tonal-balance checks, and may lack bitrate and transcode data.
          Analyze again from the <Link to="/library">Library</Link> to get a full verdict; files are measured again, never changed.</div>
      )}
      {folders.length > 0 && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <h3>Folders with the most problems</h3>
          <table><tbody>
            {folders.map(g => (
              <tr key={g.dir}><td title={g.dir}>{g.dir.split('/').slice(-2).join('/')}</td>
                <td className="num">{g.fix > 0 && <Badge tone="danger">{g.fix} fix</Badge>} {g.check > 0 && <Badge tone="warn">{g.check} check</Badge>}</td>
                <td className="num"><small>{g.total} files</small></td></tr>
            ))}
          </tbody></table>
        </div>
      )}
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
              {header('filename', 'Track', false)}{header('verdict', 'Verdict', false)}{header('integrated_lufs', 'LUFS')}
              {header('true_peak_dbtp', 'dBTP')}{header('loud_lufs', 'Loud parts')}{header('delta', 'Trim to match')}
            </tr>
          </thead>
          <tbody>
            {shown.map(r => (
              <tr key={`${r.path}-${r.id}`}>
                <td title={r.path}>{r.filename}{r.missing && <> <Badge tone="warn">Missing</Badge></>}<br />
                  <small>{when(r.measured_at)}{r.origin === 'reused' ? ' · reused' : ''}</small></td>
                <td>
                  <Badge tone={TONE[r.verdict.level]}>{LABEL[r.verdict.level]}</Badge>{' '}
                  <b>{r.verdict.headline}</b><br />
                  <small>{r.verdict.action}</small>
                  {r.verdict.findings.length > 1 && (
                    <details><summary><small>{r.verdict.findings.length - 1} more</small></summary>
                      <ul>{r.verdict.findings.slice(1).map((x, i) => <li key={i}><small>{x.text}. {x.action}</small></li>)}</ul>
                    </details>
                  )}
                </td>
                <td className="num">{num(r.integrated_lufs, 2)}<br /><small>LRA {num(r.loudness_range_lu, 1)}</small></td>
                <td className="num">{num(r.true_peak_dbtp, 2)}</td>
                <td className="num">{num(r.loud_lufs, 1)}</td>
                <td className="num">{r.verdict.trim === null ? '—' : `${signed(r.verdict.trim, 1)} dB`}</td>
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
        <small>LUFS is integrated loudness; dBTP estimates reconstructed peaks; LRA is loudness variation; Loud parts is the
          short-term loudness of the louder sections. Trim to match is the gain that would bring the song to the library
          reference; nothing is applied. A verdict is guidance from measurements, so listen before replacing a file.</small>
      </p>
    </>
  )
}
