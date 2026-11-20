---
name: dj-discover
description: Find new songs to add to one of the user's genre folders in ~/Documents/DJ Tracks. Use when the user wants new music, suggestions, "songs like my X folder", or tracks for one of their DJ projects (Serge Candel, Perry Boys). Candidates come from Last.fm data through dj-hub; Claude only reviews them.
---

# DJ discover

Candidates come from real data, never from memory. `djhub discover` reads the artists in a genre folder, asks Last.fm for similar artists, ranks them by how many of the folder's artists point to them, and drops every song already in the library. It is read-only: no files, tags or playlists change.

```sh
uv run --project ~/Projects/dj-hub/backend djhub discover "<genre folder>" [--artists N] [--tracks N (default 2)] [--json]
```

Needs `LASTFM_API_KEY` in `.env`. Never print it. If it is missing, tell the user to create a free key at https://www.last.fm/api/account/create.

Results are saved in the dj-hub database (not in the library), so they persist between sessions:

```sh
uv run --project ~/Projects/dj-hub/backend djhub candidates [--status new|wanted|dismissed|in_library] [--genre "<folder>"]
uv run --project ~/Projects/dj-hub/backend djhub mark wanted|dismissed|new ID [ID ...]
```

Each line shows the candidate ID, the "because" seeds, `[you already own N ...]`, `[check: ...]` and `[in playlist ...]` (already in one of the user's Spotify playlists). `dismissed` songs are never suggested again; `wanted` songs stay in the list until a library scan finds them in a genre folder; then they become `in_library`.

## Workflow

1. Get the genre folder names with `djhub status` (do not invent folders).
2. Run `djhub discover "<genre>"`. Show the list with the "because" reasons.
3. Review the top candidates against the project profiles in `~/Projects/dj-hub/AGENTS.md`: name the project(s) each track fits, say so when it fits none. Do not add tracks that are not in the command output.
4. Flag `[check: you may have ...]` items (other version or similar title) and `[in playlist ...]` items, so the user does not buy twice.
5. Mark what the user picks with `djhub mark wanted ...` and what they reject with `djhub mark dismissed ...`. Ask before dismissing, since it is permanent unless marked `new` again.
6. The user downloads the wanted songs: the Download button on a Discover card, or `djhub soulseek "Artist Title"` (ask first: it logs in to Soulseek, downloads up to 10 MP3 versions of 320 kbps or better into `<first download folder>/Soulseek`, and shares the `Genres` folder while connected). Then continue with the `dj-library` skill (`review`, `intake-decided`, sort the Inbox).

Last.fm returns popular tracks, which can skew to hits. Say so if results look too mainstream for the folder.
