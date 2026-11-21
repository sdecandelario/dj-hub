import { useEffect, useRef, type ReactNode } from 'react'
import { downloadCsv } from './format'

/** Search box plus "Copy list" and "Export CSV" for a filtered list (Discover, Playlists). It stays at the top of the
 *  window while the list scrolls; its height goes to `--toolbar-h` so a `.list-table` header sticks right below it. */
export function ListToolbar({ search, onSearch, placeholder, empty, copyText, csvName, csvRows, children }: {
  search: string
  onSearch: (value: string) => void
  placeholder: string
  empty: boolean
  copyText: () => string
  csvName: string
  csvRows: () => (string | number)[][]
  /** Extra filters, shown after the search box. */
  children?: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const bar = ref.current
    const parent = bar?.parentElement
    if (!bar || !parent) return
    const observer = new ResizeObserver(() => parent.style.setProperty('--toolbar-h', `${bar.offsetHeight}px`))
    observer.observe(bar)
    return () => observer.disconnect()
  }, [])
  return (
    <div ref={ref} className="row list-toolbar">
      <span className="search-wrap">
        <input className="search" placeholder={placeholder} value={search} onChange={e => onSearch(e.target.value)}
          aria-label={placeholder} />
        {search && <button className="clear" aria-label="Clear search" title="Clear" onClick={() => onSearch('')}>×</button>}
      </span>
      {children}
      <span className="spacer" />
      <button onClick={() => navigator.clipboard.writeText(copyText())} disabled={empty}>Copy list</button>
      <button onClick={() => downloadCsv(csvName, csvRows())} disabled={empty}>Export CSV</button>
    </div>
  )
}
