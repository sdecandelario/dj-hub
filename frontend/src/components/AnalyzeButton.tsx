import { isRunning, startJob, useActiveJobs } from './jobsContext'

/** Measure one song (read-only). The result shows on the Analysis page and in the Library tables. */
export function AnalyzeButton({ path }: { path: string }) {
  const jobs = useActiveJobs()
  return (
    <button className="small" disabled={isRunning(jobs, 'analyze')} title="Measure this song (files are never changed)"
      onClick={e => { e.stopPropagation(); startJob('analyze', { path }) }}>
      Analyze
    </button>
  )
}
