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
