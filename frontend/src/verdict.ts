import type { Measurement } from './api'

// One verdict per track: fix (replace or find another version), check (listen or set the gain), ok.
// Thresholds follow the downloads review (transcode gap, decode errors) so both pages agree.
export type Level = 'fix' | 'check' | 'ok'
type Finding = { level: Level | 'info'; text: string; action: string }
export type Verdict = {
  level: Level
  headline: string        // the main reason, short
  action: string          // what to do about it
  findings: Finding[]     // every reason, most severe first
  trim: number | null     // gain (dB) that would bring the track to the library reference
}

export type Context = {
  referenceLufs: number | null
  libraryLoud: number | null   // median loud-section LUFS of the view
  libraryAir: number | null    // median top-end level of the view
}

const PEAK_CEILING = -1      // dBTP: headroom target when raising gain
const TRANSCODE_GAP_DB = 85

const num = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const db = (v: number, digits = 1) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}`

export const isValid = (r: Measurement) => r.status === 'OK' &&
  [r.integrated_lufs, r.true_peak_dbtp, r.loudness_range_lu].every(num)

export const median = (values: number[]) => {
  const a = [...values].sort((x, y) => x - y)
  return a.length ? (a[Math.floor((a.length - 1) / 2)] + a[Math.floor(a.length / 2)]) / 2 : null
}

export function contextFor(rows: Measurement[], referenceLufs: number | null): Context {
  const ok = rows.filter(r => !r.missing && isValid(r))
  const typical = (key: 'loud_lufs' | 'tone_air_db') => {
    const v = ok.map(r => r[key]).filter(num)
    return v.length >= 5 ? median(v) : null
  }
  return { referenceLufs, libraryLoud: typical('loud_lufs'), libraryAir: typical('tone_air_db') }
}

const RANK: Record<Level | 'info', number> = { fix: 3, check: 2, info: 1, ok: 0 }

export function judge(row: Measurement, ctx: Context): Verdict {
  const f: Finding[] = []
  const add = (level: Finding['level'], text: string, action: string) => f.push({ level, text, action })
  const ok = isValid(row)
  const lufs = row.integrated_lufs as number
  const peak = row.true_peak_dbtp as number
  const delta = ok && ctx.referenceLufs !== null ? lufs - ctx.referenceLufs : null
  const trim = delta === null ? null : -delta

  if (row.status !== 'OK') add('fix', 'Could not be measured', 'Check the file or replace it with another version.')
  if ((row.corrupt_frames ?? 0) > 0) add('fix', `${row.corrupt_frames} decoding error(s)`, 'Replace it with another version.')
  if (num(row.hf_gap_19k_db) && row.hf_gap_19k_db > TRANSCODE_GAP_DB && row.codec !== 'flac') {
    add('fix', 'Likely a transcode: nothing above 19.5 kHz', 'Look for a better source (lossless or a true 320 kbps).')
  }
  if (num(row.bitrate_kbps) && row.codec === 'mp3') {
    if (row.bitrate_kbps < 128) add('fix', `Low bitrate (${row.bitrate_kbps} kbps)`, 'Look for a 320 kbps version.')
    else if (row.bitrate_kbps < 224) add('check', `Bitrate ${row.bitrate_kbps} kbps`, 'Prefer a 320 kbps version if you can find one.')
  }

  if (ok && delta !== null && trim !== null) {
    const headroom = PEAK_CEILING - peak               // dB of boost available before passing the ceiling
    if (trim > 0 && trim > headroom + 0.5) {
      add(trim > 3 ? 'fix' : 'check', `${db(trim)} dB would match the library but only ${Math.max(headroom, 0).toFixed(1)} dB of headroom`,
        'Raising the gain would clip: find a louder master, or accept playing it lower.')
    } else if (Math.abs(delta) > 6) {
      add('check', `${Math.abs(delta).toFixed(1)} LU ${delta < 0 ? 'quieter' : 'louder'} than the library`,
        `Set the trim to ${db(trim)} dB and compare mixing passages; another master may sit better.`)
    } else if (Math.abs(delta) > 3) {
      add('check', `${Math.abs(delta).toFixed(1)} LU ${delta < 0 ? 'quieter' : 'louder'} than the library`, `Set the trim to ${db(trim)} dB.`)
    }
  }

  if (ok && peak > 3) add('check', `True peak ${db(peak, 2)} dBTP`, 'Listen for distortion; common in loud MP3s, so only act if you hear it.')
  else if (ok && peak > 0) add('info', `True peak ${db(peak, 2)} dBTP`, 'Harmless at normal gain; keep it in mind if you raise the trim.')

  if (ok && num(row.loud_lufs) && ctx.libraryLoud !== null && delta !== null && ctx.referenceLufs !== null) {
    // Loud sections against the library, compared with how the whole song compares.
    const loudDelta = row.loud_lufs - ctx.libraryLoud
    const gap = loudDelta - delta
    if (gap <= -2) add('check', `Its loud sections are ${Math.abs(loudDelta).toFixed(1)} LU ${loudDelta < 0 ? 'below' : 'above'} the library, ${Math.abs(gap).toFixed(1)} LU less than its average suggests`,
      'It will feel quieter in a mix than its LUFS says: add a little trim.')
    else if (gap >= 2) add('info', `Loud sections hit ${gap.toFixed(1)} LU harder than its average suggests`, 'It may feel louder than its LUFS says.')
  }
  if (ok && num(row.tone_air_db) && ctx.libraryAir !== null && row.tone_air_db - ctx.libraryAir < -5) {
    add('info', `Darker than most of the library (${Math.abs(row.tone_air_db - ctx.libraryAir).toFixed(0)} dB less top end)`,
      'Dull masters feel quieter at the same LUFS; compare against another version.')
  }
  if (ok && (row.loudness_range_lu as number) > 10) add('info', 'Wide dynamics', 'Listen to intros and outros.')

  f.sort((a, b) => RANK[b.level] - RANK[a.level])
  const top = f[0]
  const level: Level = top && (top.level === 'fix' || top.level === 'check') ? top.level : 'ok'
  if (!top || top.level === 'info') {
    return { level, headline: top ? 'Fine' : 'Fine', action: trim !== null && Math.abs(trim) >= 0.5
      ? `Trim ${db(trim)} dB to match the library.` : 'Nothing to do.', findings: f, trim }
  }
  return { level, headline: top.text, action: top.action, findings: f, trim }
}

export const order = (v: Verdict) => RANK[v.level]
