import { useSyncExternalStore } from 'react'

// One place for errors nobody is waiting on (a failed click, a background action): they appear as a
// dismissible banner instead of being lost as unhandled promise rejections.

type Entry = { id: number; message: string }
let entries: Entry[] = []
let nextId = 1
const listeners = new Set<() => void>()
const emit = () => listeners.forEach(l => l())

export function reportError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error)
  entries = [...entries.filter(e => e.message !== message), { id: nextId++, message }].slice(-3)
  emit()
}

const dismiss = (id: number) => {
  entries = entries.filter(e => e.id !== id)
  emit()
}

/** Run a fire-and-forget action and show its error, if any. Resolves to undefined on failure. */
export const attempt = <T,>(promise: Promise<T>) => promise.catch(error => { reportError(error); return undefined })

const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function ErrorToasts() {
  const list = useSyncExternalStore(subscribe, () => entries)
  if (!list.length) return null
  return (
    <div className="toasts" role="alert">
      {list.map(e => (
        <div className="callout danger" key={e.id}>
          <span>{e.message}</span>
          <button className="small ghost" onClick={() => dismiss(e.id)} aria-label="Dismiss error">✕</button>
        </div>
      ))}
    </div>
  )
}
