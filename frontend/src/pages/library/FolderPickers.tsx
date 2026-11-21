import { useState } from 'react'

const NEW = '+ New…'

// Choosing "+ New…" turns the select into a text box. The name is only a choice: the folder is created
// when the batch is applied.
export function GenrePicker({ value, options, onChange, onCreate }: {
  value: string; options: string[]; onChange: (name: string) => void; onCreate: (name: string) => void
}) {
  const [typing, setTyping] = useState(false)
  if (typing) {
    const commit = (raw: string) => {
      const name = raw.trim()
      if (name) { onCreate(name); onChange(name) }
      setTyping(false)
    }
    return <input autoFocus placeholder="New genre" onBlur={e => commit(e.target.value)}
      onKeyDown={e => { if (e.key === 'Enter') commit(e.currentTarget.value); if (e.key === 'Escape') setTyping(false) }} />
  }
  return (
    <select value={value} onChange={e => (e.target.value === NEW ? setTyping(true) : onChange(e.target.value))}>
      <option value="">—</option>
      {options.map(g => <option key={g}>{g}</option>)}
      <option value={NEW}>{NEW}</option>
    </select>
  )
}

export function SessionPicker({ value, options, onChange, onCreate }: {
  value: string[]; options: string[]; onChange: (names: string[]) => void; onCreate: (name: string) => void
}) {
  const toggle = (name: string) => onChange(value.includes(name) ? value.filter(v => v !== name) : [...value, name])
  const add = (raw: string) => {
    const name = raw.trim()
    if (name) { onCreate(name); if (!value.includes(name)) onChange([...value, name]) }
  }
  return (
    <details className="picker">
      <summary>{value.length ? value.join(', ') : '—'}</summary>
      <div className="picker-menu">
        {options.map(s => (
          <label key={s}><input type="checkbox" checked={value.includes(s)} onChange={() => toggle(s)} /> {s}</label>
        ))}
        <input placeholder="+ New session" onKeyDown={e => {
          if (e.key === 'Enter') { add(e.currentTarget.value); e.currentTarget.value = '' }
        }} />
      </div>
    </details>
  )
}
