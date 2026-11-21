import { useSyncExternalStore } from 'react'
import { dismiss, getErrors, subscribe } from './errorBus'

export function ErrorToasts() {
  const list = useSyncExternalStore(subscribe, getErrors)
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
