import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type Batch, type LibraryVerdict, type LibraryVersion, type Review, type Song, type Version } from '../api'
import { useBatch } from '../components/batch'
import { PlayerBar, usePlayer, type Player } from '../components/player'
import { isRunning, startJob, useActiveJobs } from '../components/jobs'
import { Badge, Card, duration, Empty, ErrorNote, num, plural, signed } from '../components/ui'

type Filter = 'todo' | 'decided' | 'later' | 'wanted' | 'all'

const VERDICT: Record<LibraryVerdict['verdict'], { label: string; tone: string }> = {
  better: { label: 'Better than library', tone: 'ok' },
  worse: { label: 'Worse than library', tone: 'danger' },
  similar: { label: 'Similar to library', tone: 'info' },
  same: { label: 'Same as library', tone: 'warn' },
}

function VerdictBadge({ v }: { v: LibraryVerdict }) {
  const { label, tone } = VERDICT[v.verdict]
  const note = v.length_differs ? ' Different length from the library copy: maybe another edit.' : ''
  return <Badge tone={tone} title={`${v.reason}.${note}\nLibrary copy: ${v.library_path}`}>
    {label}{v.length_differs ? ' · other length' : ''}
  </Badge>
}

const isLossless = (codec: string) => ['flac', 'alac'].includes(codec) || codec.startsWith('pcm')

/** A library copy shown under the downloads, to compare and listen. */
function LibraryRow({ song, v, median, player }: {
  song: Song; v: LibraryVersion; median: number | null; player: Player
}) {
  const isPlaying = player.isPlaying(v.file_id)
  const delta = median !== null && v.integrated_lufs !== null ? v.integrated_lufs - median : null
  return (
    <tr className="library-row">
      <td></td>
      <td>
        <button className={`small${isPlaying ? ' on' : ''}`} onClick={() => player.play({ song: song.id, file: v.file_id, title: song.song, name: v.name })}>
          {isPlaying ? '❚❚' : '▶'}
        </button>
      </td>
      <td style={{ minWidth: 240 }}>
        <div title={v.path}><Badge>In library</Badge> {v.name}</div>
        <small>{v.rel_path}</small>
        {v.warnings.length > 0 && <ul className="warnings">{v.warnings.map(w => <li key={w}>{w}</li>)}</ul>}
      </td>
      <td className="num">{duration(v.duration_seconds)}</td>
      <td className="num">{isLossless(v.codec) ? <Badge tone="ok">{v.codec}</Badge> : `${v.bitrate_kbps ?? '—'} kbps`}</td>
      <td className="num">{num(v.integrated_lufs)}<br /><small>{delta === null ? '' : `${signed(delta)} vs lib`}</small></td>
      <td className="num">{num(v.true_peak_dbtp)}</td>
      <td className="num">{num(v.loudness_range_lu)}</td>
      <td className="num">{num(v.hf_gap_19k_db, 0)}</td>
    </tr>
  )
}

function VersionRow({ song, v, median, kept, onKeep, player }: {
  song: Song; v: Version; median: number | null; kept: boolean; onKeep: () => void; player: Player
}) {
  const isPlaying = player.isPlaying(v.file_id)
  const delta = median !== null && v.integrated_lufs !== null ? v.integrated_lufs - median : null
  const lossless = isLossless(v.codec)
  return (
    <tr className={`${kept ? 'kept' : ''} ${song.suggested === v.path ? 'suggested' : ''} ${v.invalid ? 'invalid' : ''}`}>
      <td>
        <input type="radio" name={`keep-${song.id}`} checked={kept} onChange={onKeep} disabled={v.invalid}
          aria-label="Keep this version" title={v.invalid ? 'Only MP3 files can be kept' : undefined} />
      </td>
      <td>
        <button className={`small${isPlaying ? ' on' : ''}`} onClick={() => player.play({ song: song.id, file: v.file_id, title: song.song, name: v.name })}>
          {isPlaying ? '❚❚' : '▶'}
        </button>
      </td>
      <td style={{ minWidth: 240 }}>
        <div title={v.path}>{v.name}</div>
        <small>
          {[v.album, v.year].filter(Boolean).join(' · ') || 'No album tag'}
          {v.version_label && ` · ${v.version_label}`}
        </small>
        {v.name_differs && <> <Badge title="Grouped with this song because the name looks the same">Named: {v.listed_as}</Badge></>}
        {v.invalid && <> <Badge tone="danger">Invalid: not MP3</Badge></>}
        {song.suggested === v.path && <> <Badge tone="accent">Suggested</Badge></>}
        {v.vs_library && <> <VerdictBadge v={v.vs_library} /></>}
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
  song: Song; median: number | null; player: Player
  onDecide: (choice: string, keep?: string | null) => void; highlight: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { if (highlight) ref.current?.scrollIntoView({ block: 'center' }) }, [highlight])
  const d = song.decision
  const keptPath = d?.choice === 'keep' ? d.keep_path : null
  const pick = song.versions.find(v => v.path === (keptPath ?? song.suggested))
  const invalid = song.versions.filter(v => v.invalid).length
  return (
    <div ref={ref} className={`song${d ? ' decided' : ''}`} style={highlight ? { borderColor: 'var(--accent)' } : undefined}>
      <header>
        <b>{song.song}</b>
        <Badge>{plural(song.versions.length, 'version')}</Badge>
        {pick?.vs_library
          ? <VerdictBadge v={pick.vs_library} />
          : song.in_library.length > 0 && <Badge tone="warn" title={song.in_library.join('\n')}>Already in library</Badge>}
        {song.wanted_by.length > 0 && (
          <Badge tone="info" title={song.wanted_by.map(w => `${w.artists.join(', ')} - ${w.title}`).join('\n')}>
            Wanted by {[...new Set(song.wanted_by.flatMap(w => w.playlists))].join(', ')}
          </Badge>
        )}
        {song.gone && <Badge tone="danger">Some files moved: review again</Badge>}
        {invalid > 0 && (
          <Badge tone="danger" title="Only MP3 files are accepted. Non-MP3 versions can only be rejected.">
            {invalid === song.versions.length ? 'No MP3 version: reject and download an MP3'
              : `${plural(invalid, 'non-MP3 version')}`}
          </Badge>
        )}
        <span className="spacer" />
        {d && <Badge tone={d.choice === 'later' ? '' : 'ok'}>
          {d.choice === 'keep' ? 'Keep 1, reject the rest' : d.choice === 'reject' ? 'Reject all' : 'Later'}
        </Badge>}
        <button className="small" disabled={!(keptPath ?? song.suggested)}
          onClick={() => onDecide('keep', keptPath ?? song.suggested)}>Keep {keptPath ? 'selected' : 'suggested'}</button>
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
              <th className="num" title="Level difference between the full signal and above 19.5 kHz. Lower is better; above 85 dB looks like a transcode.">HF gap (dB)</th>
            </tr>
          </thead>
          <tbody>
            {song.versions.map(v => (
              <VersionRow key={v.path} song={song} v={v} median={median} kept={keptPath === v.path}
                onKeep={() => onDecide('keep', v.path)} player={player} />
            ))}
            {song.library_versions?.map(v => (
              <LibraryRow key={v.path} song={song} v={v} median={median} player={player} />
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
