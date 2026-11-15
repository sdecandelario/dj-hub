import { useQuery } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { api, type Batch, type Job } from '../api'
import { useBatch } from '../components/batchContext'
import { Badge, ErrorNote, StatusBadge } from '../components/ui'
import { clickableRow, JOB_LABELS, when } from '../components/format'
import { attempt } from '../components/errorBus'

function BatchOps({ id }: { id: number }) {
  const { data } = useQuery({ queryKey: ['batches', id], queryFn: () => api.get<Batch>(`/batches/${id}`) })
  if (!data) return <small className="muted">Loading…</small>
  const rel = (p: string) => (p.startsWith(data.root + '/') ? p.slice(data.root.length + 1) : p)
  return (
    <div className="table-wrap" style={{ maxHeight: 300 }}>
      <table>
        <tbody>
          {data.ops?.map(o => (
            <tr key={o.seq}>
              <td><small>{o.label || o.action}</small></td>
              <td className="mono">{rel(o.source)}</td>
              <td className="mono">→ {rel(o.dest)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!data.ops?.length && <small className="muted">No file operations recorded.</small>}
    </div>
  )
}

function JobLog({ id }: { id: number }) {
  const { data } = useQuery({ queryKey: ['jobs', id], queryFn: () => api.get<Job>(`/jobs/${id}`) })
  return <pre className="log">{data?.log || 'No log.'}</pre>
}

export default function History() {
  const [tab, setTab] = useState<'batches' | 'jobs'>('batches')
  const [open, setOpen] = useState<number | null>(null)
  const batch = useBatch()
  const batches = useQuery({ queryKey: ['batches'], queryFn: () => api.get<Batch[]>('/batches') })
  const jobs = useQuery({ queryKey: ['jobs'], queryFn: () => api.get<Job[]>('/jobs'), refetchInterval: 5000 })

  return (
    <>
      <div className="page-head">
        <div>
          <h1>History</h1>
          <p className="muted">Every file change and every job. Applied changes can be undone (files come back from the Trash).</p>
        </div>
      </div>
      <div className="tabs">
        <button className={tab === 'batches' ? 'active' : ''} onClick={() => setTab('batches')}>File changes</button>
        <button className={tab === 'jobs' ? 'active' : ''} onClick={() => setTab('jobs')}>Jobs</button>
      </div>
      <ErrorNote error={batches.error || jobs.error} />
      {tab === 'batches' && (
        <div className="panel flush table-wrap">
          <table>
            <thead><tr><th>#</th><th>Change</th><th>Status</th><th>When</th><th></th></tr></thead>
            <tbody>
              {batches.data?.map(b => (
                <Fragment key={b.id}>
                  <tr {...clickableRow(() => setOpen(open === b.id ? null : b.id))}>
                    <td>{b.id}</td>
                    <td>{b.label}{b.legacy_id && <> <Badge>dj-library skill</Badge></>}
                      {b.error && <><br /><small className="muted">{b.error}</small></>}</td>
                    <td><StatusBadge status={b.status} /></td>
                    <td><small>{when(b.applied_at ?? b.created_at)}</small></td>
                    <td onClick={e => e.stopPropagation()}>
                      {b.can_undo && (
                        <button className="small" onClick={() => batch.preview(() => api.post<Batch>(`/batches/${b.id}/undo`))}>Undo</button>
                      )}
                    </td>
                  </tr>
                  {open === b.id && <tr><td colSpan={5}><BatchOps id={b.id} /></td></tr>}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === 'jobs' && (
        <div className="panel flush table-wrap">
          <table>
            <thead><tr><th>#</th><th>Job</th><th>Status</th><th>Result</th><th>Started</th><th></th></tr></thead>
            <tbody>
              {jobs.data?.map(j => (
                <Fragment key={j.id}>
                  <tr {...clickableRow(() => setOpen(open === j.id ? null : j.id))}>
                    <td>{j.id}</td>
                    <td>{JOB_LABELS[j.type] ?? j.type}{(Array.isArray(j.params.paths) || typeof j.params.path === 'string') && <><br /><small className="mono">{Array.isArray(j.params.paths) ? j.params.paths.join('; ') : String(j.params.path)}</small></>}</td>
                    <td><StatusBadge status={j.status} /></td>
                    <td><small>{j.total ? `${j.done}/${j.total} · ` : ''}{j.message}</small></td>
                    <td><small>{when(j.started_at ?? j.created_at)}</small></td>
                    <td onClick={e => e.stopPropagation()}>
                      {['interrupted', 'failed', 'cancelled'].includes(j.status) && !j.legacy_id && (
                        <button className="small" onClick={() => attempt(api.post(`/jobs/${j.id}/resume`).then(() => jobs.refetch()))}>Resume</button>
                      )}
                      {['running', 'queued'].includes(j.status) && (
                        <button className="small" onClick={() => attempt(api.post(`/jobs/${j.id}/cancel`))}>Cancel</button>
                      )}
                    </td>
                  </tr>
                  {open === j.id && <tr><td colSpan={6}><JobLog id={j.id} /></td></tr>}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
