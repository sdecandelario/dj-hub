import { duration } from './format'
import type { Player } from './usePlayer'

/** Small player fixed at the bottom of the page, to jump around the song. */
export function PlayerBar({ player }: { player: Player }) {
  const { track, paused, time, length } = player
  if (!track) return null
  return (
    <div className="playerbar">
      <button className="small" onClick={player.toggle} aria-label={paused ? 'Play' : 'Pause'}>{paused ? '▶' : '❚❚'}</button>
      <button className="small ghost" onClick={() => player.seekTo(time - 10)} title="Back 10 s">−10</button>
      <button className="small ghost" onClick={() => player.seekTo(time + 10)} title="Forward 10 s">+10</button>
      <div className="player-title" title={track.name}>
        <b>{track.title}</b>
        <small>{track.name}</small>
      </div>
      <span className="num muted">{duration(time)}</span>
      <input type="range" className="player-seek" min={0} max={length || 0} step={0.1} value={Math.min(time, length || 0)}
        onChange={e => player.seekTo(Number(e.target.value))} aria-label="Position" />
      <span className="num muted">{duration(length || null)}</span>
      <button className="small ghost" onClick={player.close} aria-label="Close player">✕</button>
    </div>
  )
}
