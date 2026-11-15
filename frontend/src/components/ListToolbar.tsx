import { downloadCsv } from './format'

/** Search box plus "Copy list" and "Export CSV" for a filtered list (Discover, Playlists). */
export function ListToolbar({ search, onSearch, placeholder, empty, copyText, csvName, csvRows }: {
  search: string
  onSearch: (value: string) => void
  placeholder: string
  empty: boolean
  copyText: () => string
  csvName: string
  csvRows: () => (string | number)[][]
}) {
  return (
    <div className="row" style={{ marginBottom: 10 }}>
      <input className="search" placeholder={placeholder} value={search} onChange={e => onSearch(e.target.value)}
        aria-label={placeholder} />
      <span className="spacer" />
      <button onClick={() => navigator.clipboard.writeText(copyText())} disabled={empty}>Copy list</button>
      <button onClick={() => downloadCsv(csvName, csvRows())} disabled={empty}>Export CSV</button>
    </div>
  )
}
