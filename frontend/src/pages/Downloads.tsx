import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type Batch, type Review } from '../api'
import { useBatch } from '../components/batch'
import { PlayerBar, usePlayer } from '../components/player'
import { isRunning, startJob, useActiveJobs } from '../components/jobs'
import { Card, Empty, ErrorNote, num, plural } from '../components/ui'
import { reportError } from '../components/errors'
import { SongCard } from './downloads/SongCard'

type Filter = 'todo' | 'decided' | 'later' | 'wanted' | 'all'

export default function Downloads() {
  const [params] = useSearchParams()
  const focus = params.get('song')
  const [filter, setFilter] = useState<Filter>(focus ? 'all' : 'todo')
  const [search, setSearch] = useState('')
  const jobs = useActiveJobs()
  const client = useQueryClient()
  const batch = useBatch()
  const player = usePlayer()
  const { data, error, isLoading } = useQuery({ queryKey: ['downloads'], queryFn: () => api.get<Review | null>('/downloads') })
  const decide = useMutation({
    mutationFn: ({ song, choice, keep }: { song: string; choice: string; keep?: string | null }) =>
      api.put(`/downloads/decisions/${song}`, { choice, keep_path: keep ?? null }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['downloads'] }),
  })
  const reviewing = isRunning(jobs, 'review_downloads')

  const songs = data?.songs ?? []
  const decided = songs.filter(s => s.decision && s.decision.choice !== 'later')
  const counts = {
    todo: songs.filter(s => !s.decision).length,
    decided: decided.length,
    later: songs.filter(s => s.decision?.choice === 'later').length,
    wanted: songs.filter(s => s.wanted_by.length).length,
    all: songs.length,
  }
  const q = search.toLowerCase()
  const shown = songs.filter(s => ({
    todo: !s.decision, decided: !!s.decision && s.decision.choice !== 'later', later: s.decision?.choice === 'later',
    wanted: s.wanted_by.length > 0, all: true,
  }[filter]) && s.song.toLowerCase().includes(q))

  const suggestable = shown.filter(x => !x.decision && x.suggested)
  const keepAllSuggested = async () => {
    try {
      for (const s of suggestable) {
        await api.put(`/downloads/decisions/${s.id}`, { choice: 'keep', keep_path: s.suggested })
      }
    } catch (error) {
      reportError(error)   // stop at the first failure, but still show what was decided
    }
    client.invalidateQueries({ queryKey: ['downloads'] })
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Downloads</h1>
          <p className="muted">
            Pick the best version of each song. The kept one goes to <b>00 Inbox</b>, the others to <b>00 Rejected</b> for a final check.
            {data && ` Reviewed ${data.generated} from ${data.sources.join(', ')}.`}
          </p>
        </div>
        <button className="primary" onClick={() => startJob('review_downloads')} disabled={reviewing}>
          {reviewing ? 'Reviewing…' : 'Review downloads now'}
        </button>
      </div>
      <ErrorNote error={error} />
      {data?.skipped_recent.length ? (
        <div className="callout info">{plural(data.skipped_recent.length, 'file')} changed in the last {data.settle_seconds} s were skipped (still downloading?).</div>
      ) : null}
      {isLoading && <Empty>Loading…</Empty>}
      {!isLoading && !data && <Empty>No review yet. Click <b>Review downloads now</b>; the first run measures every file and takes a while.</Empty>}
      {data && (
        <>
          <div className="cards">
            <Card label="To decide" value={counts.todo} selected={filter === 'todo'} onClick={() => setFilter('todo')} />
            <Card label="Decided" value={counts.decided} hint="Ready to move" selected={filter === 'decided'} onClick={() => setFilter('decided')} />
            <Card label="Later" value={counts.later} selected={filter === 'later'} onClick={() => setFilter('later')} />
            <Card label="Wanted by a playlist" value={counts.wanted} selected={filter === 'wanted'} onClick={() => setFilter('wanted')} />
            <Card label="All songs" value={counts.all} selected={filter === 'all'} onClick={() => setFilter('all')} />
          </div>
          <div className="row" style={{ marginBottom: 12 }}>
            <input className="search" placeholder="Search songs" value={search} onChange={e => setSearch(e.target.value)} />
            <span className="muted">Library median: {data.library_median === null ? 'no complete library analysis yet' : `${num(data.library_median)} LUFS`}</span>
            <span className="spacer" />
            {filter === 'todo' && suggestable.length > 0 && (
              <button onClick={keepAllSuggested}>Keep suggested for {suggestable.length} song{suggestable.length === 1 ? '' : 's'}</button>
            )}
          </div>
          {shown.map(s => (
            <SongCard key={s.id} song={s} median={data.library_median} player={player} highlight={s.id === focus}
              onDecide={(choice, keep) => decide.mutate({ song: s.id, choice, keep })} />
          ))}
          {!shown.length && <Empty>Nothing here.</Empty>}
        </>
      )}
      <div className="bottombar">
        <PlayerBar player={player} />
        {decided.length > 0 && (
          <div className="decisionbar">
            <b>{plural(decided.length, 'song')} decided</b>
            <span className="muted">
              {decided.filter(s => s.decision?.choice === 'keep').length} to 00 Inbox ·{' '}
              {decided.reduce((n, s) => n + s.versions.length - (s.decision?.choice === 'keep' ? 1 : 0), 0)} file(s) to 00 Rejected
            </span>
            <span className="spacer" />
            <button className="primary" onClick={() => batch.preview(() => api.post<Batch>('/downloads/preview', {}))}>
              Preview the move
            </button>
          </div>
        )}
      </div>
    </>
  )
}
