# DJ Hub

One local app for the DJ library in `~/Documents/DJ Tracks`: Spotify playlists against the library, downloads review, new-song discovery, loudness analysis and every file change (always previewed, undoable).

- **Playlists**: which tracks of your Spotify playlists are missing, need a check (other version, similar title), or are already in the library. Each track shows its DJ project, and whether a matching download is waiting.
- **Downloads**: measures new files in the Nicotine and `~/Downloads` folders, groups the versions of each song, flags transcodes, decode errors, other edits and compilations, and suggests the best one. You listen, pick, and move: the kept version goes to `00 Inbox`, the others to `00 Rejected/<song>`.
- **Discover**: new songs for a genre folder. Last.fm finds artists similar to the ones you already have there, ranks them by how many of your artists point to them, and lists their top tracks you do not own. Mark each one Want or Dismiss (dismissed songs never come back). Songs already in one of your Spotify playlists are flagged. Nothing here changes your files.
- **Library**: browse Inbox, Rejected, genres and sessions; select a song to play it, see its copies, playlists and loudness history; set its genre, add it to a session, send it to the Trash. Sort the whole Inbox in one go (an Inbox song already in the library is flagged: replace the old genre copy, or discard the new file to `00 Rejected`), fix missing tags, and rename Inbox files (artist and title).
- **Analysis**: loudness runs (LUFS, true peak, LRA), compared with a reference run. Start a run from the Library (selected songs, a folder or the whole library); the Analysis page shows the runs and results. Every run is kept.
- **Rekordbox**: the tracks Rekordbox's export logs say are missing, and where each file is now (moved by a batch, replaced, or found by name). Read only.
- **History**: every job and every file change. Applied changes can be undone.

It runs natively on the Mac (no Docker): it needs direct access to the music folders, the Trash and Finder.

## Setup

```sh
brew install uv node ffmpeg
make setup
make start              # http://127.0.0.1:8000
```

`make dev` runs the API with auto-reload and the Vite dev server (http://127.0.0.1:5173).

## Spotify

Playlists are read through the Spotify Web API, which needs a login:

1. In your app at https://developer.spotify.com/dashboard add the redirect URI `http://127.0.0.1:8000/api/spotify/callback`.
2. Copy `.env.dist` to `.env` (git-ignored) and fill in `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`.
3. Settings → **Connect Spotify**. The login is saved in `data/spotify_token.json` (git-ignored, readable only by you).

## Last.fm

Discover needs a free Last.fm API key (https://www.last.fm/api/account/create; the callback URL can stay empty). Put it in `.env` as `LASTFM_API_KEY`. The key is never printed.

## Safety

- Audio data and Rekordbox are never modified, and measuring only reads. Tags and names change only in previewed batches (all undoable): moving a kept download to `00 Inbox` writes its artist and title tags, "Fix tags" fills missing artist/title tags (and, if you ask, the genre tag), renaming a file in `00 Inbox` renames it to `Artist - Title.mp3` with matching tags, and `retag` corrects the artist or title tag of songs already sorted (tags only, never file names).
- Every file change is planned first and shown for confirmation. Nothing is deleted: removals go to the Trash. Each applied change is a batch you can undo from History.
- A song keeps exactly one genre folder; sessions hold copies.
- If files change between the preview and Apply, nothing is done and you are asked to preview again.
- Downloads changed in the last 2 minutes are skipped (possibly still downloading).
- Rekordbox finds tracks by path: after moving a song Rekordbox already imported, re-link it there.

## Command line

The Claude skills in `.claude/skills/` (`dj-library`, `dj-discover`) use the same logic through `djhub`:

```sh
uv run --project ~/Projects/dj-hub/backend djhub status
uv run --project ~/Projects/dj-hub/backend djhub apply plan.json            # dry run
uv run --project ~/Projects/dj-hub/backend djhub apply plan.json --apply
uv run --project ~/Projects/dj-hub/backend djhub undo --apply
```

- **Soulseek**: the Download button on a Discover or Playlists row, or "Download selected" for several ticked songs (or `djhub soulseek "Artist Title" ...`), searches Soulseek in one session for MP3 files of 320 kbps or better and downloads up to 10 versions of each song into the `Soulseek` folder inside the first download folder, so the Downloads page can pick the best one. It connects only while it runs, and shares `Genres` (read-only) meanwhile. Minimum bitrate and versions per song are in Settings.

Other commands: `scan`, `find`, `remove`, `fix-tags`, `retag`, `intake`, `intake-decided`, `dupes`, `history`, `review`, `analyze`, `refresh-playlists`, `scan-library`, and for new music `discover`, `candidates`, `mark`, `soulseek`.

## Configuration

Secrets live in `.env` (copy `.env.dist`); the app and `djhub` read it at start, and a variable set in the shell wins. The other variables are optional:

| Variable | Default |
| --- | --- |
| `DJ_TRACKS_ROOT` | `~/Documents/DJ Tracks` |
| `DJ_TRASH` | `~/.Trash` |
| `DJ_SOURCES` | Nicotine downloads and `~/Downloads` (or set them in Settings) |
| `DJ_REKORDBOX_DIR` | `~/Documents/rekordbox` (Rekordbox export logs, read only) |
| `DJ_HUB_DB` | `data/dj-hub.db` in the project (git-ignored) |
| `DJ_HUB_FRONTEND` | Where the app sends you after the Spotify login (set by `make dev` to the Vite server) |

## Development

```sh
make test               # backend tests (temporary folders, real ffmpeg) + frontend type check and build
make lint               # ruff (backend), oxlint and knip (frontend: unused files, exports, dependencies)
make migration m="..."  # after changing backend/app/models.py
```

- `backend/app/core`: tags, names, audio, library rules, download ranking and matching (no database or web code).
- `backend/app/integrations`: the Spotify, Last.fm and Soulseek clients (network, login file, env vars).
- `backend/app/services`: use cases (library batches, analysis, downloads review, playlists).
- `backend/app/api`: HTTP routes under `/api`. `backend/app/jobs.py`: background jobs with progress.
- `frontend/src/pages`: one file per page.
