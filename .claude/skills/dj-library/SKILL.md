---
name: dj-library
description: Organize the user's DJ music library in ~/Documents/DJ Tracks into genre and session folders. Use when the user wants to review new downloads (Nicotine or ~/Downloads) and pick the best version, sort new tracks, add or remove songs from a session, change a song's genre, find where a song is, check for duplicates, or undo a library change. Rekordbox playlists are later created from these folders.
---

# DJ library

The library lives in `~/Documents/DJ Tracks`. All file work goes through the DJ Hub app (`~/Projects/dj-hub`), whose `djhub` command has the same commands as the old `djlib.py`:

```sh
uv run --project ~/Projects/dj-hub/backend djhub <command>
```

Applied changes are stored as batches in the DJ Hub database, so they also show (and can be undone) on the app's History page. The user can do the same work in the web app (`make start` in `~/Projects/dj-hub`, then http://127.0.0.1:8000). `djlib.py` next to this file is the old version: do not use it. To find new songs for a genre folder, use the `dj-discover` skill.

## Layout and rules

```
DJ Tracks/
  00 Inbox/                      chosen downloads, waiting for a genre
  00 Rejected/<Artist - Title>/  download versions not chosen, kept for a final check
  Genres/<genre>/                every song lives in exactly ONE genre folder
  Sessions/<session>/            a session (copies), e.g. "Sessions/New Year Party 2026"
```

Download folders (`SOURCES`): `~/.local/share/nicotine/downloads` and `~/Downloads`.

- A song's genre copy is its safe copy. Session copies are extras.
- Into a genre: **move** from `00 Inbox`. Use **copy** when the source is a session folder, so the session stays complete.
- Into a session: **copy**, normally from the song's genre folder. The plan target is `Sessions/<name>` (`"to": "Sessions/New Year Party 2026"`); a new name creates a new session folder inside `Sessions/`. A bare name is refused.
- Any other top-level folder, or a file directly in `Sessions/`, shows as **Unsorted** in `status`: move it into the right place.
- Changing genre: **move** from the old genre folder to the new one.
- `00 Rejected` is not part of the library: `status`, `scan` and `dupes` ignore it.
- The script refuses anything that would leave a song with no genre or with two genres, and never deletes: `remove` and `undo` send files to the Trash.
- Do not rename files or edit tags or audio. Rekordbox finds tracks by file path, so after Rekordbox has imported a file, moving or renaming it makes it show as missing. Mention this when the user changes the genre of, or removes, a song they may have already imported. The session folders were moved into `Sessions/` on 2026-11-08, so session playlists imported before that need re-linking or re-importing in Rekordbox.
- Nicotine shares the whole `DJ Tracks` folder, so `00 Inbox` and `00 Rejected` are shared too.

## Genres

The genre list is the folders under `Genres/` (run `status` to see them). Do not invent a new genre folder without asking.

Choose by artist and track, using your music knowledge, the `genre_tag` (often generic or wrong, so only a hint) and the project profiles in `~/Projects/dj-hub/AGENTS.md`. When a song fits two genres, pick the one where the user would look for it first. Put uncertain picks in a separate "please check" list instead of guessing quietly.

## Commands

| Command | What it does |
| --- | --- |
| `status` | Count per folder, songs with no genre, songs in two genres |
| `scan [FOLDER]` | JSON of songs to sort: by default every song with no genre; with FOLDER (e.g. `"00 Inbox"`), the songs in that folder |
| `find WORDS...` | Every copy of songs matching artist/title/filename words |
| `apply PLAN.json [--apply]` | Run a plan of copies and moves |
| `remove PATH... [--apply]` | Send copies to the Trash (files or folders, relative to the library) |
| `intake PICKS.json [--apply]` | Move reviewed downloads: the kept version to `00 Inbox`, the others to `00 Rejected/<song>` |
| `intake-decided [--apply]` | Same, for the songs the user decided on the app's Downloads page |
| `review` | Measure and group the downloads (read-only); results show on the Downloads page |
| `history` | Recent batches with their IDs |
| `index` | JSON of every library file (used by the downloads review) |
| `undo [--batch ID] [--apply]` | Revert the last applied change, or a given batch (number, or an old djlib batch name) |
| `dupes` | Same file under two names, and same artist+title in different files |

Plan file format (write it to the session scratchpad, not the library):

```json
[
  {"source": "00 Inbox/Boy Harsher - Pain.mp3", "to": "Genres/Post-Punk & Dark Wave", "action": "move"},
  {"source": "00 Inbox/Boy Harsher - Pain.mp3", "to": "Sessions/New Year Party 2026", "action": "copy"}
]
```

`source` is always the song's path when the plan starts; the script follows a move made earlier in the same plan.

## Workflow

Every change has two steps:

1. Run without `--apply` (a dry run) and show the user a short summary: songs per target folder, any skips, and any PROBLEM lines explained in plain words. For long plans, group by folder instead of listing every file.
2. Run again with `--apply` only after the user approves. Report the batch ID and that `undo` can revert it.

Typical tasks:

- **Review downloads:**
  1. Run `djhub review` (read-only; new files are measured, earlier ones come from the cache). Report files, songs, identical copies, likely transcodes, songs already in the library and songs wanted by a playlist.
  2. The user opens the Downloads page in DJ Hub, listens, and picks Keep / Reject all / Later per song. They can apply the move there themselves.
  3. If they ask you to do it: run `intake-decided` as a dry run and summarize: songs to the Inbox, versions to Rejected, NOTE lines (already in the library or a possible upgrade) and PROBLEM lines. Apply after approval.
  4. Then sort the Inbox (below). For a "possible upgrade", ask whether to replace the old genre copy; remember that Rekordbox will lose the old path.
  5. Final check: when the user is happy, `remove "00 Rejected"` (or one song folder) sends the rejected versions to the Trash.
- **Sort the inbox:** `scan "00 Inbox"`, propose a genre per song (table: artist, title, proposed genre, unsure marker), let the user adjust, write the plan, dry run, apply.
- **Add to a session:** `find` the songs, then a plan that copies each song from its genre folder into the session folder. If a song has no genre yet, sort it first.
- **Remove from a session:** `remove "Sessions/<session>/<file>"`.
- **Where is a song:** `find`.
- **Library check:** `status` and `dupes`. Duplicates are only reported; ask the user which copy to keep, then use `remove`.

After applying, remind the user once how to update Rekordbox: drag the folder from Finder onto **Playlists** to create a playlist named after it, or drag the new files into the existing playlist.

## Testing

To try commands without touching the real library or database, set `DJ_TRACKS_ROOT`, `DJ_TRASH`, `DJ_SOURCES` and `DJ_HUB_DB` to paths in the scratchpad.
