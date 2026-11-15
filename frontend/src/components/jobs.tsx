import { useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type Job } from '../api'
import { JOB_LABELS, StatusBadge } from './ui'

// Which cached queries to refresh when a job of this type finishes.
const REFRESH: Record<string, string[]> = {
  analyze: ['analysis', 'files', 'file', 'summary'],
  review_downloads: ['downloads', 'summary', 'playlists', 'tracks', 'files'],
  spotify_refresh: ['playlists', 'tracks', 'summary', 'downloads'],
  library_scan: ['files', 'tree', 'summary', 'playlists', 'tracks', 'file'],
  match_playlists: ['playlists', 'tracks', 'summary', 'downloads', 'file'],
  discover: ['candidates'],
}

const JobsContext = createContext<Job[]>([])
export const useActiveJobs = () => useContext(JobsContext)

/** Subscribes to /api/events and keeps the list of active jobs; refreshes data when jobs finish. */
export function JobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Job[]>([])
  const seen = useRef(new Map<number, string>())
  const client = useQueryClient()

  useEffect(() => {
    // Browsers allow ~6 connections per site, so only the visible tab keeps the stream open.
    let source: EventSource | null = null
    const onJobs = (event: Event) => {
      const list = JSON.parse((event as MessageEvent).data) as Job[]
      for (const job of list) {
        const before = seen.current.get(job.id)
        if (before !== job.status) {
          seen.current.set(job.id, job.status)
          if (!['queued', 'running'].includes(job.status)) {
            for (const key of REFRESH[job.type] ?? []) client.invalidateQueries({ queryKey: [key] })
            client.invalidateQueries({ queryKey: ['jobs'] })
          }
        }
      }
      setJobs(list)
    }
    const sync = () => {
      if (document.hidden) {
        source?.close()
        source = null
      } else if (!source) {
        source = new EventSource('/api/events')
        source.addEventListener('jobs', onJobs)
        // Catch up on anything that finished while the tab was hidden.
        client.invalidateQueries()
      }
    }
    sync()
    document.addEventListener('visibilitychange', sync)
    return () => {
      document.removeEventListener('visibilitychange', sync)
      source?.close()
    }
  }, [client])

  return <JobsContext.Provider value={jobs}>{children}</JobsContext.Provider>
}

export function JobBar() {
  const jobs = useActiveJobs()
  const [hidden, setHidden] = useState<Set<number>>(new Set())
  const visible = jobs.filter(j => !hidden.has(j.id))
  if (!visible.length) return null
  return (
    <div className="jobbar">
      {visible.map(job => {
        const active = job.status === 'running' || job.status === 'queued'
        const pct = job.total ? Math.round((100 * job.done) / job.total) : 0
        return (
          <div className="job" key={job.id}>
            <div className="row">
              <b>{JOB_LABELS[job.type] ?? job.type}</b>
              <StatusBadge status={job.status} />
              <span className="spacer" />
              {active ? (
                <button className="small" onClick={() => api.post(`/jobs/${job.id}/cancel`)}>Cancel</button>
              ) : (
                <button className="small ghost" onClick={() => setHidden(new Set(hidden).add(job.id))}>✕</button>
              )}
            </div>
            <small>{job.total ? `${job.done}/${job.total} · ` : ''}{job.message}</small>
            {active && (
              <div className={`progress${job.total ? '' : ' indeterminate'}`}>
                <div style={job.total ? { width: `${pct}%` } : undefined} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** Start a job and return its id. */
export const startJob = (type: Job['type'], params: Record<string, unknown> = {}) =>
  api.post<{ id: number }>('/jobs', { type, params })

export const isRunning = (jobs: Job[], type: Job['type']) =>
  jobs.some(j => j.type === type && (j.status === 'running' || j.status === 'queued'))
