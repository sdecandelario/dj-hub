# AGENTS.md

## About this project

DJ Hub is a personal tool: one user, one Mac, never in production and never shared. So:

- Prefer the simplest, cleanest design. Refactor, rename and restructure freely when it makes the code better; there is no one to stay compatible with. No compatibility shims, deprecated paths, old formats or "just in case" options.
- Delete dead code and unused features (`make lint` runs ruff, oxlint and knip to find them).
- The app database (`data/dj-hub.db` in the project, git-ignored) is personal history, not precious: schema changes may be breaking, migrations may be squashed, and it may be deleted and rebuilt (scan the library and refresh the playlists). Keeping backups of it is not needed.
- This freedom does not cover the music: the library in `~/Documents/DJ Tracks` and the Rekordbox library are irreplaceable, so the rules below stay exactly as they are. The same goes for secrets (Spotify keys and login, `LASTFM_API_KEY`).

## Rules

Use English for all project documentation, code identifiers, comments, filenames, schema fields, CLI messages, and UI text. Preserve original track titles, artist names, source paths, and historical provenance verbatim.

Audio analysis is read-only. Never modify music files, tags, or the Rekordbox library, with one exception: when a batch moves a kept download to 00 Inbox, it writes the artist and title ID3 tags (and fills an empty album or year from another version of the song), so Rekordbox shows them correctly. A second exception is the "tags" batch (`djhub fix-tags`, or the Library page): it fills missing artist and title tags from the file name and, only when asked, sets the genre tag to the genre folder name. A third is the "rename" batch (Library page, 00 Inbox only): the user edits artist or title, and the file is renamed to `Artist - Title.mp3` with matching tags. It changes only the 00 Inbox file, lists each change in the preview, and undo restores the old values. File moves only happen through batches (`app/services/library.py`): plan, show the user, apply after approval. Nothing is deleted; removals go to the Trash.

## Working in this project

- Safe to run without asking: `make test`, `make lint`, `uv run --project backend pytest`, `npm --prefix frontend run build`.
- Tests use temporary folders and databases (`backend/tests/conftest.py`); never point tests at the real library.
- Ask before running anything that applies a batch (`djhub ... --apply`, `POST /api/batches/{id}/apply`) on the real library.
- Ask before refreshing Spotify playlists: it calls Spotify and rewrites the stored playlists.
- `djhub discover` is read-only but calls Last.fm (`LASTFM_API_KEY` env var, never print it). Candidates come from Last.fm data; only the fit review against the projects below is done by Claude.
- Never read or print `~/.zprofile`, `~/.zshrc` or `data/spotify_token.json`. They hold the Spotify keys (`SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`), `LASTFM_API_KEY` and the Spotify login. The login file sits in the git-ignored `data/` folder with the database.
- The database is `data/dj-hub.db` (override with `DJ_HUB_DB`). Schema changes need an Alembic migration: `make migration m="..."` (migrations run with foreign keys off, see `backend/app/migrations/env.py`).
- Layout: `backend/app/core` is the file, tag and matching logic (keep it free of database and web code); `integrations` holds the Spotify and Last.fm clients (network, login file, env vars); `services` are the use cases; `api` the HTTP routes; `cli.py` the `djhub` command used by the skills in `.claude/skills/` (`dj-library`, `dj-discover`). The skills live only there, so change a skill in the same commit as the command it calls. They load when Claude Code starts in this folder. `frontend/src/pages` has one file per page.
- Artist names in the profiles below must match Spotify's spelling.

## DJ projects

The user plays in three DJ projects. When suggesting tracks, reviewing a playlist, or sorting missing tracks, say which project(s) a track fits (Juventudes Gilderianas excluded, see below). A track can fit more than one project. If a track fits none, say so instead of forcing it.

The profiles below come from the reference playlists listed with each project, read through the Spotify API. Treat them as guidance, not strict rules, and update them when the playlists change.

### 1. Serge Candel (solo)

The user's own project. Dark, driving, body music: post-punk, cold wave, new wave, EBM, dark synth-pop, and dark techno / electro.

Reference playlists:

| Playlist | Spotify ID | Focus |
| --- | --- | --- |
| Serge Candel | `3PuCqjzr4B2fWcsd2SGKp7` | Core sound of the project |
| Feel the darkness | `1U0L91CdWLM5HNz5gIITqr` | International dark: post-punk, goth, EBM, industrial |
| Spanish darkness | `0y8lq7C5y2vtmOxSSAuwzp` | Spanish-language dark wave, old and new |
| Keep it warm | `2K52sYJ72EQ8VT5sk49m2k` | Warm-up: italo disco, hi-NRG, 80s synth-pop |

Reference artists:

- Modern post-punk / dark wave: Rendez Vous, She Past Away, Home Front, Boy Harsher, Cold Cave, Kontravoid, Buzz Kull, TR/ST, The Soft Moon, Drab Majesty, Twin Tribes, Motorama, Soviet Soviet, Human Tetris, Molchat Doma, Lebanon Hanover, Sextile, Preoccupations, Interpol, Grave Pleasures, Beastmilk.
- Classic post-punk / goth / new wave: Joy Division, The Cure, Sisters of Mercy, Killing Joke, Bauhaus, Siouxsie and the Banshees, Fad Gadget, Depeche Mode, Bronski Beat, Wire, The Chameleons.
- EBM / industrial / aggrotech: Nitzer Ebb, DAF, Gabi Delgado, Front 242, Combichrist, Covenant, And One, VNV Nation, Hocico, Project Pitchfork, KMFDM, Ministry, Nine Inch Nails, Nachtmahr.
- Dark electronic / electroclash: Crystal Castles, The Prodigy, Vitalic, Gesaffelstein, Miss Kittin, The Hacker, Qual.
- Spanish scene: Futuro Terror, Antiguo Régimen, VVV [Trippin'you], Luz Futuro, Mausoleo, Depresión Sonora, El Último Vecino, La Plata, Paralisis Permanente, Aviador Dro, Los Carniceros Del Norte, Ortopedia Técnica, Nueve Desconocidos, Alcalá Norte, Dame Area, Erik Urano.
- Warm-up (Keep it warm): Patrick Cowley, Trans-X, Lee Marrow, Ken Laszlo, Magazine 60, The Flirts, Bobby O, Yazoo, Mind Enterprises.

Fits: minor keys, cold synths, deep vocals, mechanical 4/4 or motorik beats, roughly 110–135 BPM.

Does not fit: mainstream pop, rumba, reggae, party anthems with no dark edge.

### 2. Juventudes Gilderianas

A shared project with no defined music line yet: it has no reference playlist and no profile. Do not suggest tracks for it or name it as a fit; only the other two projects get that treatment. When the user defines its sound, add a profile here.

### 3. Perry Boys

A shared project focused on a New Year's Eve party. The goal is a full dance floor: electronic music, rumba, and petardeo (Spanish slang for over-the-top, sing-along party hits).

Reference playlist: Perry Boys, Spotify ID `1FURH6wFT0gwsbOZpMWSy3`. Very varied, with little artist repetition.

Reference artists:

- Rumba and Spanish party music: Peret, Los Chichos, Las Grecas, Los Rumberos Catalanes, Rumba Tres, Estopa, Junco, Raphael, Raffaella Carrà, El Coleta, Los Bengala, Gameboyz.
- Spanish indie and new club pop: Joe Crepúsculo, Grande Amore, Parquesvr, LA ÉLITE, ROSALÍA.
- Petardeo and big pop/dance hits: GIGI D'AGOSTINO, Boney M., Baccara, Cerrone, Shaggy, Sophie Ellis-Bextor, Modjo, Dead Or Alive, Billy Idol, Electric Six.
- House, French touch, and electroclash: Daft Punk, Justice, Soulwax, Digitalism, Simian Mobile Disco, Boys Noize, The Prodigy, Faithless, Groove Armada, Armand Van Helden, Disclosure, Polo & Pan, Todd Terje.
- Dance-punk and loud guitars: Gang Of Four, IDLES, Fat Dog, Viagra Boys, Death From Above 1979, LCD Soundsystem.
- The dark side, kept from the solo project for peak moments: DAF, Gabi Delgado, Nitzer Ebb, Ministry, Boy Harsher, Nine Inch Nails, Gary Numan, Depeche Mode, VVV [Trippin'you], El Columpio Asesino.

Fits: tracks people know and sing along to, fun and upbeat, easy to mix between genres. Dark tracks are welcome if they are danceable.

Does not fit: slow, introspective, or obscure tracks that need context to work.

### Overlap

The projects share artists, so one track can belong to several projects. Examples: Boy Harsher, Depeche Mode, and Home Front appear in both the solo and Perry Boys playlists, and Mind Enterprises appears in Keep it warm and Perry Boys. When a track is in more than one playlist, note it so the user does not buy it twice.
