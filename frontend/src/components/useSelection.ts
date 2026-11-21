import { useState } from 'react'

/** A set of ticked row keys with toggle, tick-all and clear. */
export function useSelection() {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  return {
    selected,
    toggle: (key: string) => setSelected(prev => {
      const next = new Set(prev)
      if (!next.delete(key)) next.add(key)
      return next
    }),
    setAll: (keys: string[], on: boolean) => setSelected(on ? new Set(keys) : new Set()),
    clear: () => setSelected(new Set()),
  }
}
