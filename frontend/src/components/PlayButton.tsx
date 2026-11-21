import type { Player, Track } from './usePlayer'

/** The play / pause button used in every table. */
export function PlayButton({ player, track }: { player: Player; track: Track }) {
  const playing = player.isPlaying(track.file)
  return (
    <button className={`small${playing ? ' on' : ''}`} aria-label={`${playing ? 'Pause' : 'Play'} ${track.title}`}
      onClick={() => player.play(track)}>
      {playing ? '❚❚' : '▶'}
    </button>
  )
}
