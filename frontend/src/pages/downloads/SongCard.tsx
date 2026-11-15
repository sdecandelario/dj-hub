import { useEffect, useRef } from 'react'
import type { LibraryVerdict, LibraryVersion, Song, Version } from '../../api'
import { PlayButton } from '../../components/PlayButton'
import type { Player } from '../../components/usePlayer'
import { Badge } from '../../components/ui'
import { duration, num, plural, signed } from '../../components/format'

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

type Measured = Pick<Version, 'duration_seconds' | 'codec' | 'bitrate_kbps' | 'integrated_lufs' | 'true_peak_dbtp'
  | 'loudness_range_lu' | 'hf_gap_19k_db'>

/** The measurement columns shared by a downloaded version and a library copy. */
function StatCells({ v, median, hfTitle }: { v: Measured; median: number | null; hfTitle?: boolean }) {
  const delta = median !== null && v.integrated_lufs !== null ? v.integrated_lufs - median : null
  return (
    <>
      <td className="num">{duration(v.duration_seconds)}</td>
      <td className="num">{isLossless(v.codec) ? <Badge tone="ok">{v.codec}</Badge> : `${v.bitrate_kbps ?? '—'} kbps`}</td>
      <td className="num">{num(v.integrated_lufs)}<br /><small>{delta === null ? '' : `${signed(delta)} vs lib`}</small></td>
      <td className="num">{num(v.true_peak_dbtp)}</td>
      <td className="num">{num(v.loudness_range_lu)}</td>
      <td className="num" title={hfTitle ? 'Level difference between the full signal and above 19.5 kHz. Lower means more detail.' : undefined}>
        {num(v.hf_gap_19k_db, 0)}
      </td>
    </>
  )
}

/** A library copy shown under the downloads, to compare and listen. */
function LibraryRow({ song, v, median, player }: {
  song: Song; v: LibraryVersion; median: number | null; player: Player
}) {
  return (
    <tr className="library-row">
      <td></td>
      <td>
        <PlayButton player={player} track={{ song: song.id, file: v.file_id, title: song.song, name: v.name }} />
      </td>
      <td style={{ minWidth: 240 }}>
        <div title={v.path}><Badge>In library</Badge> {v.name}</div>
        <small>{v.rel_path}</small>
        {v.warnings.length > 0 && <ul className="warnings">{v.warnings.map(w => <li key={w}>{w}</li>)}</ul>}
      </td>
      <StatCells v={v} median={median} />
    </tr>
  )
}

function VersionRow({ song, v, median, kept, onKeep, player }: {
  song: Song; v: Version; median: number | null; kept: boolean; onKeep: () => void; player: Player
}) {
  return (
    <tr className={`${kept ? 'kept' : ''} ${song.suggested === v.path ? 'suggested' : ''} ${v.invalid ? 'invalid' : ''}`}>
      <td>
        <input type="radio" name={`keep-${song.id}`} checked={kept} onChange={onKeep} disabled={v.invalid}
          aria-label="Keep this version" title={v.invalid ? 'Only MP3 files can be kept' : undefined} />
      </td>
      <td>
        <PlayButton player={player} track={{ song: song.id, file: v.file_id, title: song.song, name: v.name }} />
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
      <StatCells v={v} median={median} hfTitle />
    </tr>
  )
}

export function SongCard({ song, median, player, onDecide, highlight }: {
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
