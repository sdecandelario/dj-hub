// Typed access to the DJ Hub API (/api). Shapes mirror backend/app/api/*.py.

class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${url}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    let message = response.statusText
    try {
      const data = await response.json()
      message = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, message)
  }
  try {
    return (await response.json()) as T
  } catch {
    throw new ApiError(response.status, `Unexpected response from ${method} /api${url} (is the server up to date?)`)
  }
}

export const api = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body: unknown = {}) => request<T>('POST', url, body),
  put: <T>(url: string, body: unknown) => request<T>('PUT', url, body),
  patch: <T>(url: string, body: unknown) => request<T>('PATCH', url, body),
  del: <T>(url: string) => request<T>('DELETE', url),
}

export const audioUrl = (fileId: number) => `/api/files/${fileId}/audio`

// --- Types ----------------------------------------------------------------

export type Job = {
  id: number
  type: 'analyze' | 'review_downloads' | 'spotify_refresh' | 'library_scan' | 'match_playlists' | 'discover'
  params: Record<string, unknown>
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'interrupted'
  done: number
  total: number
  message: string
  summary: Record<string, unknown>
  created_at: string
  started_at: string | null
  finished_at: string | null
  log?: string
}

export type Step = { action: 'copy' | 'move' | 'skip'; source: string; dest: string; note: string; label: string
  /** ID3 tags written after the move (null removes), and tags written only when empty. */
  tags?: Record<string, string | null>; fill_tags?: Record<string, string> }

export type Batch = {
  id: number
  kind: 'apply' | 'remove' | 'intake' | 'undo' | 'tags' | 'rename'
  status: 'preview' | 'running' | 'applied' | 'partial' | 'undone' | 'discarded' | 'failed'
  label: string
  created_at: string
  applied_at: string | null
  error: string
  undoes_id: number | null
  root: string
  can_undo: boolean
  plan: { kind: string; steps: Step[]; problems: string[]; notes: string[] }
  ops?: { seq: number; action: string; label: string; source: string; dest: string }[]
  steps?: number
}

export type ApplyResult = { id: number; status: string; error: string; done: number; kind: string; warnings?: string[] }

type Loudness = {
  path: string
  status: string
  integrated_lufs: number | null
  true_peak_dbtp: number | null
  loudness_range_lu: number | null
  measured_at: string
}

export type LibraryFile = {
  id: number
  path: string
  rel_path: string
  name: string
  area: 'library' | 'download' | 'other'
  kind: 'inbox' | 'rejected' | 'genre' | 'session' | 'unsorted' | ''
  folder: string
  artist: string
  title: string
  genre_tag: string
  bpm: string
  size: number
  present: boolean
  quick_fp: string | null
  loudness?: Loudness | null
}

export type Measurement = {
  id: number
  job_id: number | null
  path: string
  filename: string
  sha256: string | null
  measured_at: string
  origin: string
  full: boolean
  status: string
  error: string
  integrated_lufs: number | null
  true_peak_dbtp: number | null
  loudness_range_lu: number | null
  duration_seconds: number | null
  codec: string
  sample_rate_hz: number | null
  channels: number | null
  corrupt_frames?: number | null
  bitrate_kbps?: number | null
  hf_gap_17k_db?: number | null
  hf_gap_19k_db?: number | null
  loud_lufs?: number | null
  momentary_max_lufs?: number | null
  tone_low_db?: number | null
  tone_mid_db?: number | null
  tone_presence_db?: number | null
  tone_air_db?: number | null
  run_id?: number
  missing?: boolean
}

export type FileDetail = LibraryFile & {
  copies: LibraryFile[]
  history: Measurement[]
  playlists: { playlist: string; title: string; artists: string[]; status: string }[]
}

export type Tree = {
  root: string
  folders: { kind: string; folder: string; count: number }[]
  genres: string[]
  sessions: string[]
}

type Run = {
  id: number
  label: string
  scope: 'file' | 'folder' | 'selection' | 'test'
  complete: boolean
  status: string
  config: { input: string; [key: string]: unknown }
  created_at: string
  files: number
  median_lufs: number | null
}

export type AnalysisOverview = { runs: Run[]; references: Run[]; current: Measurement[] }

export type Version = {
  path: string
  name: string
  file_id: number
  source: string
  size: number
  mtime_ns: string
  sha256: string
  status: string
  error: string
  integrated_lufs: number | null
  true_peak_dbtp: number | null
  loudness_range_lu: number | null
  duration_seconds: number | null
  codec: string
  sample_rate_hz: number | null
  bitrate_kbps: number | null
  corrupt_frames: number
  tag_artist: string
  tag_title: string
  album: string
  year: string
  has_art: boolean
  hf_gap_19k_db: number | null
  version_label: string
  /** Set when this file was grouped here because its name looks like the same song. */
  name_differs?: boolean
  listed_as?: string
  identical_to: string[]
  same_audio_as: string[]
  likely_transcode: boolean
  other_edit: boolean
  /** Not an MP3: shown with a notice, can only be rejected. */
  invalid?: boolean
  warnings: string[]
  rank: number
  /** Compared with the best library copy; missing when the song is not in the library. */
  vs_library?: LibraryVerdict
}

export type LibraryVerdict = {
  verdict: 'better' | 'worse' | 'similar' | 'same'
  reason: string
  library_path: string
  length_differs: boolean
}

export type LibraryVersion = Pick<Version, 'path' | 'name' | 'file_id' | 'sha256' | 'status' | 'integrated_lufs'
  | 'true_peak_dbtp' | 'loudness_range_lu' | 'duration_seconds' | 'codec' | 'bitrate_kbps' | 'album' | 'year'
  | 'hf_gap_19k_db' | 'likely_transcode' | 'warnings'> & { rel_path: string; folder: string; kind: string }

export type Song = {
  id: string
  artist: string
  title: string
  song: string
  suggested: string | null
  in_library: string[]
  /** Files with different names were grouped as one song. */
  grouped_by_name?: boolean
  /** Measured library copies, best first (missing in reviews made before this check existed). */
  library_versions?: LibraryVersion[]
  versions: Version[]
  gone: boolean
  decision: { choice: 'keep' | 'reject' | 'later'; keep_path: string | null; decided_at: string } | null
  wanted_by: { spotify_id: string; title: string; artists: string[]; playlists: string[]; status: string }[]
}

export type Review = {
  review_id: number
  created_at: string
  generated: string
  sources: string[]
  library_median: number | null
  median_run: number | null
  skipped_recent: string[]
  settle_seconds: number
  songs: Song[]
}

export type PlaylistInfo = {
  id: string
  name: string
  owner: string
  cover: string | null
  source: string
  possibly_truncated: boolean
  project: string
  tracked: boolean
  refreshed_at: string | null
  counts: { have: number; maybe: number; missing: number; downloaded: number; waiting: number; total: number }
}

export type PlaylistTrack = {
  spotify_id: string
  title: string
  artists: string[]
  duration_ms: number | null
  position: number
  status: 'have' | 'maybe' | 'missing'
  match: { path: string; relative_path: string; title: string; artist: string; note: string } | null
  download: { song_key: string; status: string } | null
  downloaded: boolean
  playlists: string[]
  projects: string[]
}

export type Candidate = {
  id: number
  genre: string
  artist: string
  title: string
  status: 'new' | 'wanted' | 'dismissed'
  score: number
  /** Artists in the genre folder that point to this one. */
  because: string[]
  /** Tracks by this artist (under any spelling) already in the library. */
  you_own: number
  check: { artist: string; title: string; relative_path: string; note: string } | null
  in_playlists: { playlist: string; project: string }[]
}

export type Settings = {
  root: string
  trash: string
  db: string
  sources: string[]
  sources_locked: boolean
  settle_seconds: number
  workers: number
  missing_tools: string[]
}

export type SpotifyStatus = { keys: boolean; logged_in: boolean; redirect_uri: string }

export type Summary = {
  library_files: number
  inbox: number
  rejected: number
  unsorted: number
  missing: number
  check: number
  waiting_downloads: number
  marked_downloaded: number
  review_songs: number
  review_pending: number
  review_decided: number
  review_generated: string | null
  recent_jobs: Job[]
  recent_batches: { id: number; label: string; status: string; created_at: string; kind: string }[]
  decisions: number
}
