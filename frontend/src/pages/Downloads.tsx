import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, audioUrl, type Batch, type Review, type Song, type Version } from '../api'
import { useBatch } from '../components/batch'
import { isRunning, startJob, useActiveJobs } from '../components/jobs'
import { Badge, Card, duration, Empty, ErrorNote, num, plural, signed } from '../components/ui'

type Filter = 'todo' | 'decided' | 'later' | 'wanted' | 'all'

/** One audio element for the page. Switching between versions of the same song keeps the position. */
function usePlayer() {
  const audio = useRef<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState<{ song: string; file: number } | null>(null)
  useEffect(() => {
    const el = new Audio()
    audio.current = el
    el.onended = () => setPlaying(null)
    return () => { el.pause(); el.src = '' }
  }, [])
  const play = (song: string, file: number) => {
    const el = audio.current
    if (!el) return
    if (playing?.file === file) {
      el.pause()
      setPlaying(null)
      return
    }
    const keep = playing?.song === song ? el.currentTime : 0
    el.src = audioUrl(file)
    el.onloadedmetadata = () => { el.currentTime = Math.min(keep, el.duration || keep) }
    el.play().catch(() => setPlaying(null))
    setPlaying({ song, file })
  }
  const seek = (delta: number) => { if (audio.current) audio.current.currentTime += delta }
  return { playing, play, seek }
}

function VersionRow({ song, v, median, kept, onKeep, player }: {
  song: Song; v: Version; median: number | null; kept: boolean; onKeep: () => void; player: ReturnType<typeof usePlayer>
}) {
  const isPlaying = player.playing?.file === v.file_id
  const delta = median !== null && v.integrated_lufs !== null ? v.integrated_lufs - median : null
  const lossless = ['flac', 'alac'].includes(v.codec) || v.codec.startsWith('pcm')
  return (
    <tr className={`${kept ? 'kept' : ''} ${song.suggested === v.path ? 'suggested' : ''}`}>
      <td>
        <input type="radio" name={`keep-${song.id}`} checked={kept} onChange={onKeep} aria-label="Keep this version" />
      </td>
      <td>
        <button className={`small${isPlaying ? ' on' : ''}`} onClick={() => player.play(song.id, v.file_id)}>
          {isPlaying ? '❚❚' : '▶'}
        </button>
      </td>
      <td style={{ minWidth: 240 }}>
        <div title={v.path}>{v.name}</div>
        <small>
          {[v.album, v.year].filter(Boolean).join(' · ') || 'No album tag'}
          {v.version_label && ` · ${v.version_label}`}
        </small>
        {song.suggested === v.path && <> <Badge tone="accent">Suggested</Badge></>}
        {v.identical_to.length > 0 && <> <Badge title={v.identical_to.join(', ')}>Identical copy</Badge></>}
        {v.same_audio_as.length > 0 && <> <Badge title={v.same_audio_as.join(', ')}>Same audio, other tags</Badge></>}
        {v.warnings.length > 0 && <ul className="warnings">{v.warnings.map(w => <li key={w}>{w}</li>)}</ul>}
      </td>
      <td className="num">{duration(v.duration_seconds)}</td>
      <td className="num">{lossless ? <Badge tone="ok">{v.codec}</Badge> : `${v.bitrate_kbps ?? '—'} kbps`}</td>
      <td className="num">{num(v.integrated_lufs)}<br /><small>{delta === null ? '' : `${signed(delta)} vs lib`}</small></td>
      <td className="num">{num(v.true_peak_dbtp)}</td>
      <td className="num">{num(v.loudness_range_lu)}</td>
      <td className="num" title="Level difference between the full signal and above 19.5 kHz. Lower means more detail.">
        {num(v.hf_gap_19k_db, 0)}
      </td>
    </tr>
  )
}

function SongCard({ song, median, player, onDecide, highlight }: {
  song: Song; median: number | null; player: ReturnType<typeof usePlayer>
  onDecide: (choice: string, keep?: string | null) => void; highlight: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { if (highlight) ref.current?.scrollIntoView({ block: 'center' }) }, [highlight])
  const d = song.decision
  const keptPath = d?.choice === 'keep' ? d.keep_path : null
  return (
    <div ref={ref} className={`song${d ? ' decided' : ''}`} style={highlight ? { borderColor: 'var(--accent)' } : undefined}>
      <header>
        <b>{song.song}</b>
        <Badge>{plural(song.versions.length, 'version')}</Badge>
        {song.in_library.length > 0 && <Badge tone="warn" title={song.in_library.join('\n')}>Already in library</Badge>}
        {song.wanted_by.length > 0 && (
          <Badge tone="info" title={song.wanted_by.map(w => `${w.artists.join(', ')} - ${w.title}`).join('\n')}>
            Wanted by {[...new Set(song.wanted_by.flatMap(w => w.playlists))].join(', ')}
          </Badge>
        )}
        {song.gone && <Badge tone="danger">Some files moved: review again</Badge>}
        <span className="spacer" />
        {d && <Badge tone={d.choice === 'later' ? '' : 'ok'}>
          {d.choice === 'keep' ? 'Keep 1, reject the rest' : d.choice === 'reject' ? 'Reject all' : 'Later'}
        </Badge>}
        <button className="small" onClick={() => onDecide('keep', keptPath ?? song.suggested)}>Keep {keptPath ? 'selected' : 'suggested'}</button>
        <button className="small" onClick={() => onDecide('reject')}>Reject all</button>
        <button className="small" onClick={() => onDecide('later')}>Later</button>
        {d && <button className="small ghost" onClick={() => onDecide('clear')}>Clear</button>}
      </header>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Keep</th><th></th><th>File</th><th className="num">Length</th><th className="num">Quality</th>
              <th className="num">LUFS</th><th className="num">dBTP</th><th className="num">LRA</th>
              <th className="num" title="Lower is better">HF gap</th>
            </tr>
          </thead>
          <tbody>
            {song.versions.map(v => (
              <VersionRow key={v.path} song={song} v={v} median={median} kept={keptPath === v.path}
                onKeep={() => onDecide('keep', v.path)} player={player} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

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

  const keepAllSuggested = async () => {
    for (const s of shown.filter(x => !x.decision && x.suggested)) {
      await api.put(`/downloads/decisions/${s.id}`, { choice: 'keep', keep_path: s.suggested })
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
            {filter === 'todo' && shown.some(s => s.suggested) && (
              <button onClick={keepAllSuggested}>Keep suggested for all {shown.length} shown</button>
            )}
          </div>
          {shown.map(s => (
            <SongCard key={s.id} song={s} median={data.library_median} player={player} highlight={s.id === focus}
              onDecide={(choice, keep) => decide.mutate({ song: s.id, choice, keep })} />
          ))}
          {!shown.length && <Empty>Nothing here.</Empty>}
        </>
      )}
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
    </>
  )
}
