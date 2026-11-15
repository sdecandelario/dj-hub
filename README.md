# DJ Hub

One local app for the DJ library in `~/Documents/DJ Tracks`. It replaces `DJ_Playlist_Checker`, `DJ_Loudness_Analyzer` and the file logic of the old dj-library script.

- **Playlists**: which tracks of your Spotify playlists are missing, need a check (other version, similar title), or are already in the library. Each track shows its DJ project, and whether a matching download is waiting.
- **Downloads**: measures new files in the Nicotine and `~/Downloads` folders, groups the versions of each song, flags transcodes, decode errors, other edits and compilations, and suggests the best one. You listen, pick, and move: the kept version goes to `00 Inbox`, the others to `00 Rejected/<song>`.
- **Discover**: new songs for a genre folder. Last.fm finds artists similar to the ones you already have there, ranks them by how many of your artists point to them, and lists their top tracks you do not own. Mark each one Want or Dismiss (dismissed songs never come back). Songs already in one of your Spotify playlists are flagged. Nothing here changes your files.
- **Library**: browse Inbox, Rejected, genres and sessions; select a song to play it, see its copies, playlists and loudness history; set its genre, add it to a session, send it to the Trash. Sort the whole Inbox in one go.
- **Analysis**: loudness runs (LUFS, true peak, LRA), compared with a reference run. Start a run from the Library (selected songs, a folder or the whole library); the Analysis page shows the runs and results. Every run is kept.
- **History**: every job and every file change. Applied changes can be undone.

It runs natively on the Mac (no Docker): it needs direct access to the music folders, the Trash and Finder.

## Setup

```sh
brew install uv node ffmpeg
make setup
make start              # http://127.0.0.1:8000
```

The history of the old projects was imported on 2026-11-08 (`make import-legacy`, kept for reference; the old folders are gone).

`make dev` runs the API with auto-reload and the Vite dev server (http://127.0.0.1:5173).

## Spotify

Without keys, the public embed page is read (first 100 tracks per playlist). For full playlists:

1. In your app at https://developer.spotify.com/dashboard add the redirect URI `http://127.0.0.1:8000/api/spotify/callback`.
2. Export `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in the shell that starts the app (for example in `~/.zprofile`).
3. Settings → **Connect Spotify**. The login is saved in `~/.config/dj_playlist_checker/spotify_token.json` (the same file the old checker used, so an existing login keeps working).

## Last.fm

Discover needs a free Last.fm API key (https://www.last.fm/api/account/create; the callback URL can stay empty). Export it as `LASTFM_API_KEY` in the shell that starts the app (for example in `~/.zshrc`). The key is never printed.

## Safety

- Audio files, tags and Rekordbox are never modified. Measuring only reads.
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

Other commands: `scan`, `find`, `remove`, `intake`, `intake-decided`, `dupes`, `index`, `history`, `review`, `analyze`, `refresh-playlists`, `scan-library`, `import-legacy`, and for new music `discover`, `candidates`, `mark`.

## Configuration

| Variable | Default |
| --- | --- |
| `DJ_TRACKS_ROOT` | `~/Documents/DJ Tracks` |
| `DJ_TRASH` | `~/.Trash` |
| `DJ_SOURCES` | Nicotine downloads and `~/Downloads` (or set them in Settings) |
| `DJ_HUB_DB` | `~/.local/share/dj-hub/dj-hub.db` |

## Development

```sh
make test               # backend tests (temporary folders, real ffmpeg) + frontend type check and build
make migration m="..."  # after changing backend/app/models.py
```

- `backend/app/core`: pure logic ported from the old scripts (tags, names, audio, library rules, download ranking, Spotify, matching).
- `backend/app/services`: use cases (library batches, analysis, downloads review, playlists, legacy import).
- `backend/app/api`: HTTP routes under `/api`. `backend/app/jobs.py`: background jobs with progress.
- `frontend/src/pages`: one file per page.
