import { useEffect, useRef, useState } from 'react'
import { audioUrl } from '../api'

export type Track = { song: string; file: number; title: string; name: string }

/** One audio element for the page. Switching between versions of the same song keeps the position. */
export function usePlayer() {
  const audio = useRef<HTMLAudioElement | null>(null)
  const [track, setTrack] = useState<Track | null>(null)
  const [paused, setPaused] = useState(true)
  const [time, setTime] = useState(0)
  const [length, setLength] = useState(0)
  useEffect(() => {
    const el = new Audio()
    audio.current = el
    el.onplay = () => setPaused(false)
    el.onpause = () => setPaused(true)
    el.ontimeupdate = () => setTime(el.currentTime)
    el.ondurationchange = () => setLength(Number.isFinite(el.duration) ? el.duration : 0)
    return () => { el.pause(); el.src = '' }
  }, [])
  const toggle = () => {
    const el = audio.current
    if (!el || !track) return
    if (el.paused) el.play().catch(() => setPaused(true))
    else el.pause()
  }
  const play = (next: Track) => {
    const el = audio.current
    if (!el) return
    if (track?.file === next.file) return toggle()
    const keep = track?.song === next.song ? el.currentTime : 0
    el.src = audioUrl(next.file)
    el.onloadedmetadata = () => { el.currentTime = Math.min(keep, el.duration || keep) }
    el.play().catch(() => setPaused(true))
    setTime(keep)
    setTrack(next)
  }
  const seekTo = (seconds: number) => {
    const el = audio.current
    if (!el) return
    el.currentTime = Math.max(0, Math.min(seconds, length || seconds))
    setTime(el.currentTime)
  }
  const close = () => {
    const el = audio.current
    if (el) { el.pause(); el.removeAttribute('src'); el.load() }
    setTrack(null)
  }
  const isPlaying = (file: number) => track?.file === file && !paused
  return { track, paused, time, length, play, toggle, seekTo, close, isPlaying }
}

export type Player = ReturnType<typeof usePlayer>
