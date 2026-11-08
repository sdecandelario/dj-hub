import type { Measurement } from '../api'
import { num, when } from './ui'

const W = 600, H = 300, L = 50, R = 15, T = 15, B = 40

type Point = { lufs: number; peak: number; label: string; flag: boolean }

function lufsScale(points: Point[], ref: number | null) {
  const values = points.map(p => p.lufs).concat(ref ?? [])
  const lo = Math.floor(Math.min(...values)) - 1
  const hi = Math.ceil(Math.max(...values)) + 1
  return { lo, hi, x: (v: number) => L + ((v - lo) / (hi - lo)) * (W - L - R) }
}

function XAxis({ lo, hi, x }: { lo: number; hi: number; x: (v: number) => number }) {
  return (
    <>
      <path className="axis" d={`M${L} ${T}V${H - B}H${W - R}`} fill="none" />
      {[0, 1, 2, 3, 4].map(i => {
        const v = lo + ((hi - lo) * i) / 4
        return <text key={i} x={x(v)} y={H - B + 16} textAnchor="middle">{v.toFixed(1)}</text>
      })}
      <text x={(L + W - R) / 2} y={H - 6} textAnchor="middle">Integrated loudness (LUFS)</text>
    </>
  )
}

export function LoudnessScatter({ points, reference }: { points: Point[]; reference: number | null }) {
  if (!points.length) return <p className="muted">No valid measurements for present files.</p>
  const s = lufsScale(points, reference)
  const peaks = points.map(p => p.peak)
  const bottom = -Math.max(2, Math.ceil(-Math.min(...peaks)))
  const top = Math.max(2, Math.ceil(Math.max(...peaks)))
  const y = (v: number) => H - B - ((v - bottom) / (top - bottom)) * (H - B - T)
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Loudness against true peak">
      <XAxis {...s} />
      {[0, 1, 2, 3, 4].map(i => {
        const v = bottom + ((top - bottom) * i) / 4
        return <text key={i} x={L - 6} y={y(v) + 4} textAnchor="end">{v.toFixed(1)}</text>
      })}
      <text x={8} y={T + 4}>dBTP</text>
      <path className="zero" d={`M${L} ${y(0)}H${W - R}`} />
      {reference !== null && <path className="ref" d={`M${s.x(reference)} ${T}V${H - B}`} />}
      {points.map((p, i) => (
        <circle key={i} className={`dot${p.flag ? ' flag' : ''}`} cx={s.x(p.lufs)} cy={y(p.peak)} r={4}>
          <title>{`${p.label}: ${num(p.lufs, 2)} LUFS, ${num(p.peak, 2)} dBTP`}</title>
        </circle>
      ))}
    </svg>
  )
}

export function LoudnessHistogram({ points, reference }: { points: Point[]; reference: number | null }) {
  if (!points.length) return <p className="muted">No valid measurements for present files.</p>
  const s = lufsScale(points, reference)
  const bins = Array.from({ length: Math.max(1, s.hi - s.lo) }, () => 0)
  for (const p of points) bins[Math.min(bins.length - 1, Math.floor(p.lufs - s.lo))]++
  const max = Math.max(...bins)
  const w = (W - L - R) / bins.length
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Loudness distribution">
      <XAxis {...s} />
      <text x={L - 6} y={T + 4} textAnchor="end">{max}</text>
      <text x={8} y={T + 20}>tracks</text>
      {bins.map((n, i) => (
        <rect key={i} className="bar" x={s.x(s.lo + i) + 1} width={Math.max(1, w - 2)}
          y={H - B - (n / max) * (H - B - T)} height={(n / max) * (H - B - T)}>
          <title>{`${s.lo + i} to ${s.lo + i + 1} LUFS: ${n}`}</title>
        </rect>
      ))}
      {reference !== null && <path className="ref" d={`M${s.x(reference)} ${T}V${H - B}`} />}
    </svg>
  )
}

/** Integrated loudness of one file over time. */
export function HistoryChart({ rows }: { rows: Measurement[] }) {
  const ok = rows.filter(r => typeof r.integrated_lufs === 'number')
  if (ok.length < 2) return null
  const w = 340, h = 90, pad = 8
  const values = ok.map(r => r.integrated_lufs as number)
  const lo = Math.min(...values) - 0.5, hi = Math.max(...values) + 0.5
  const x = (i: number) => pad + (i / (ok.length - 1)) * (w - 2 * pad)
  const y = (v: number) => h - pad - ((v - lo) / (hi - lo)) * (h - 2 * pad)
  return (
    <svg className="chart" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Loudness history">
      <path d={ok.map((r, i) => `${i ? 'L' : 'M'}${x(i)} ${y(r.integrated_lufs as number)}`).join('')}
        fill="none" stroke="var(--accent)" strokeWidth={2} />
      {ok.map((r, i) => (
        <circle key={r.id} className="dot" cx={x(i)} cy={y(r.integrated_lufs as number)} r={3}>
          <title>{`${when(r.measured_at)}: ${num(r.integrated_lufs, 2)} LUFS`}</title>
        </circle>
      ))}
    </svg>
  )
}

export type { Point }
