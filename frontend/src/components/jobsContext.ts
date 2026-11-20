import { useQuery } from '@tanstack/react-query'
import { createContext, useContext } from 'react'
import { api, type Job } from '../api'
import { attempt } from './errorBus'

export const JobsContext = createContext<Job[]>([])
export const useActiveJobs = () => useContext(JobsContext)

/** Start a job and return its id (undefined, with the error shown, when it could not start). */
export const startJob = (type: Job['type'], params: Record<string, unknown> = {}) =>
  attempt(api.post<{ id: number }>('/jobs', { type, params }))

export const isRunning = (jobs: Job[], type: Job['type']) =>
  jobs.some(j => j.type === type && (j.status === 'running' || j.status === 'queued'))

/** The latest Soulseek download job per search query ("Artist Title"): live while running, as left when finished. */
export function useSoulseekJobs() {
  const live = useActiveJobs().filter(j => j.type === 'soulseek_download')
  const recent = useQuery({
    queryKey: ['jobs', 'soulseek_download'],
    queryFn: () => api.get<Job[]>('/jobs?type=soulseek_download&limit=100'),
  })
  const byQuery = new Map<string, Job>()
  for (const job of [...(recent.data ?? []), ...live]) {   // oldest first, so the newest wins
    const query = String(job.params.query ?? '')
    if (!byQuery.has(query) || byQuery.get(query)!.id < job.id) byQuery.set(query, job)
  }
  return byQuery
}
