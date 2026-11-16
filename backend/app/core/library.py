"""The DJ library layout and every file change.

Layout under the library root:
  00 Inbox/                      chosen downloads, waiting for a genre
  00 Rejected/<Artist - Title>/  download versions not chosen (final check)
  Genres/<genre>/                every song lives in exactly one genre folder
  Sessions/<session>/            a session: extra copies, any number per song
  files at the root, other folders  unsorted

Rules: never delete (removals go to the Trash), never edit audio, tags only in batches,
a song keeps exactly one genre. Every change is planned first (`plan_*`),
shown to the user, and only then run with `execute`.
"""
import datetime as dt
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .audio import audio_hash, quick_fingerprint
from .names import guess_from_filename, normalize, song_folder_name, track_file_name
from .tags import read_tags, write_tags

AUDIO = {".mp3", ".wav", ".aif", ".aiff", ".flac", ".m4a"}
GENRES, INBOX, REJECTED, SESSIONS = "Genres", "00 Inbox", "00 Rejected", "Sessions"
RESERVED = {GENRES, INBOX, REJECTED, SESSIONS}
KIND_LABELS = {"genre": "Genres", "session": "Sessions", "inbox": "Inbox",
               "unsorted": "Unsorted", "rejected": "Rejected (final check)"}


# --- Scanning -----------------------------------------------------------------


def classify(rel):
    """(kind, folder name) for a path relative to the root.

    kind is 'genre', 'session', 'inbox', 'rejected' or 'unsorted'.
    """
    parts = Path(rel).parts
    if len(parts) < 2:
        return "unsorted", "(root)"
    top = parts[0]
    if top == GENRES:
        return ("genre", parts[1]) if len(parts) >= 3 else ("unsorted", GENRES)
    if top == INBOX:
        return "inbox", INBOX
    if top == REJECTED:
        return "rejected", parts[1] if len(parts) >= 3 else REJECTED
    if top == SESSIONS:
        return ("session", parts[1]) if len(parts) >= 3 else ("unsorted", SESSIONS)
    return "unsorted", top


def describe_file(path):
    """Tags with filename fallback for one file (artist, title, genre_tag, bpm)."""
    path = Path(path)
    tags = read_tags(path) if path.suffix.lower() == ".mp3" else {}
    guess = guess_from_filename(path.stem)
    return {
        "artist": tags.get("artist") or guess.get("artist", ""),
        "title": tags.get("title") or guess.get("title", ""),
        "genre_tag": tags.get("genre", ""), "bpm": tags.get("bpm", ""),
    }


def scan(root, cache=None):
    """Every audio file in the library. `cache` maps an absolute path to a previous
    record with size/mtime_ns; unchanged files reuse its fingerprint and tags."""
    root = Path(root)
    cache = cache or {}
    tracks = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if (not path.is_file() or path.suffix.lower() not in AUDIO
                or any(p.startswith(".") for p in rel.parts)):
            continue
        try:
            stat = path.stat()
            kind, folder = classify(rel)
            old = cache.get(str(path))
            if old and old.get("size") == stat.st_size and str(old.get("mtime_ns")) == str(stat.st_mtime_ns) \
                    and old.get("fp"):
                info = {k: old.get(k) or "" for k in ("artist", "title", "genre_tag", "bpm")}
                fp = old["fp"]
            else:
                info = describe_file(path)
                fp = quick_fingerprint(path)
        except OSError:   # removed during the scan, or not downloaded from iCloud yet
            continue
        tracks.append({"path": str(rel), "abs": str(path), "kind": kind, "folder": folder, "fp": fp,
                       "size": stat.st_size, "mtime_ns": str(stat.st_mtime_ns), **info})
    return tracks


def active(copies):
    """Copies that count as part of the library (rejected versions do not)."""
    return [c for c in copies if c["kind"] != "rejected"]


def by_song(tracks):
    songs = {}
    for track in tracks:
        songs.setdefault(track["fp"], []).append(track)
    return songs


def genre_folders(copies):
    return sorted({c["folder"] for c in copies if c["kind"] == "genre"})


# --- Read-only reports -------------------------------------------------------------


def status(tracks):
    songs = {fp: active(c) for fp, c in by_song(tracks).items()}
    songs = {fp: c for fp, c in songs.items() if c}
    folders = {}
    for t in tracks:
        folders[(t["kind"], t["folder"])] = folders.get((t["kind"], t["folder"]), 0) + 1
    return {
        "files": len(tracks),
        "songs": len(songs),
        "folders": [{"kind": k, "folder": f, "count": n} for (k, f), n in sorted(folders.items())],
        "no_genre": [c[0] for c in songs.values() if not genre_folders(c)],
        "multi_genre": [{"artist": c[0]["artist"], "title": c[0]["title"], "genres": genre_folders(c)}
                        for c in songs.values() if len(genre_folders(c)) > 1],
    }


def to_sort(tracks, folder=None):
    """Songs to sort: by default every song without a genre; with `folder`, the songs in it."""
    songs = by_song([t for t in tracks if t["kind"] != "rejected"])
    out = []
    for copies in songs.values():
        if folder:
            picked = [c for c in copies if c["path"].startswith(folder.rstrip("/") + "/")]
            if not picked:
                continue
        elif genre_folders(copies):
            continue
        else:
            picked = copies
        first = picked[0]
        out.append({"source": first["path"], "artist": first["artist"], "title": first["title"],
                    "genre_tag": first["genre_tag"], "bpm": first["bpm"],
                    "genres": genre_folders(copies),
                    "also_in": sorted({c["path"] for c in copies} - {first["path"]})})
    out.sort(key=lambda s: (normalize(s["artist"]), normalize(s["title"])))
    return out


def find(tracks, words):
    words = normalize(" ".join(words)).split()
    hits = []
    for copies in by_song(tracks).values():
        hay = " ".join(normalize(f"{c['artist']} {c['title']} {Path(c['path']).stem}") for c in copies)
        if all(w in hay for w in words):
            hits.append(copies)
    return hits


def dupes(tracks):
    songs = by_song([t for t in tracks if t["kind"] != "rejected"])
    same_file = []
    for copies in songs.values():
        per_folder = {}
        for c in copies:
            per_folder.setdefault(str(Path(c["path"]).parent), []).append(c["path"])
        same_file += [{"folder": f, "files": p} for f, p in per_folder.items() if len(p) > 1]
    by_name = {}
    for copies in songs.values():
        key = (normalize(copies[0]["artist"]), normalize(copies[0]["title"]))
        if key[1]:
            by_name.setdefault(key, []).append(copies)
    same_name = [{"artist": g[0][0]["artist"], "title": g[0][0]["title"], "files": [c[0]["path"] for c in g]}
                 for g in by_name.values() if len(g) > 1]
    return {"same_file": same_file, "same_name": same_name}


# --- Plans ---------------------------------------------------------------------------


@dataclass
class Step:
    action: str        # copy | move | skip
    source: str        # absolute path
    dest: str          # absolute path ('' for skip)
    note: str = ""
    label: str = ""    # intake: inbox | reject; undo: what is being reverted
    tags: dict = field(default_factory=dict)         # ID3 values to set after the move (None removes)
    fill_tags: dict = field(default_factory=dict)    # ID3 values to set only when the file has none
    tags_before: dict | None = None                  # filled when run: what the tags were


@dataclass
class Plan:
    kind: str
    steps: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def runnable(self):
        return [s for s in self.steps if s.action != "skip"]

    def to_dict(self):
        return {"kind": self.kind, "steps": [asdict(s) for s in self.steps],
                "problems": self.problems, "notes": self.notes}

    @classmethod
    def from_dict(cls, data):
        return cls(data["kind"], [Step(**s) for s in data["steps"]], data["problems"], data["notes"])


def stamp():
    return dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _check_target(to):
    """(kind, name) for a plan target, or ValueError."""
    parts = Path(to).parts
    bad = lambda name: name in ("", ".", "..") or name.startswith(".")
    if len(parts) == 2 and parts[0] == GENRES and not bad(parts[1]):
        return "genre", parts[1]
    if len(parts) == 2 and parts[0] == REJECTED and not bad(parts[1]):
        return "rejected", parts[1]
    if len(parts) == 1 and parts[0] == INBOX:
        return "inbox", INBOX
    if len(parts) == 2 and parts[0] == SESSIONS and not bad(parts[1]):
        return "session", parts[1]
    if len(parts) == 1 and not bad(parts[0]) and parts[0] not in RESERVED:
        raise ValueError(f"sessions live in {SESSIONS}/: use {SESSIONS}/{parts[0]!s}, got {to!r}")
    raise ValueError(f"target must be {GENRES}/<name>, {SESSIONS}/<name>, {INBOX} "
                     f"or {REJECTED}/<song>, got {to!r}")


def _inside_root(root, rel):
    path = (Path(root) / rel).resolve()
    if Path(root).resolve() not in path.parents:
        raise ValueError(f"path outside the library: {rel}")
    return path


def _same_file(a, b):
    """True when two paths are the same file (a case-only rename on a case-insensitive disk)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def plan_apply(root, tracks, items):
    """Copies and moves inside the library.

    items: [{"source": rel path, "to": "Genres/X" | "00 Inbox" | "Sessions/<name>", "action": "copy"|"move",
             optional "artist" and "title": rename an Inbox file while moving it}]
    `source` is the song's path when the plan starts; later steps follow earlier moves.
    """
    return _ApplyPlanner(root, tracks).run(items)


class _ApplyPlanner:
    """State of one `plan_apply`: what earlier items of the same plan already did. A problem with an item
    is a ValueError; the item is then skipped and the problem listed."""

    def __init__(self, root, tracks):
        self.root = Path(root)
        self.songs = by_song(tracks)
        self.fp_of = {t["path"]: t["fp"] for t in tracks}
        self.planned = {}   # (target folder, fp) -> new file, so a plan cannot add a song twice
        self.located = {}   # original source -> where an earlier step of this plan moved it
        self.gone = set()   # files an earlier step moved away
        self.genres = {fp: set(genre_folders(copies)) for fp, copies in self.songs.items()}
        self.plan = Plan("apply")

    def run(self, items):
        for item in items:
            try:
                self._add(item)
            except ValueError as error:
                self.plan.problems.append(str(error))
        return self.plan

    def _parse(self, item):
        """(source, target folder, action, target kind, target name) of an item, or ValueError."""
        source, to, action = item.get("source", ""), item.get("to", ""), item.get("action", "copy")
        to_kind, to_name = _check_target(to)
        _inside_root(self.root, source)
        if action not in ("copy", "move"):
            raise ValueError(f"unknown action {action!r}")
        if source not in self.fp_of:
            raise ValueError(f"not a library audio file: {source}")
        return source, str(Path(to)), action, to_kind, to_name

    @staticmethod
    def _check_move_out(source, kind, action, to_kind):
        if action == "move" and kind == "genre" and to_kind != "genre":
            raise ValueError(f"{source}: moving out of a genre folder would leave the song without a genre; "
                             "use copy")

    def _check_genre(self, source, fp, kind, folder, action, to_kind, to_name):
        """A song keeps one genre folder: adding a second one is refused."""
        if to_kind != "genre":
            return
        after = set(self.genres[fp])
        if action == "move" and kind == "genre":
            after.discard(folder)
        after.add(to_name)
        if len(after) > 1:
            raise ValueError(f"{source}: would be in genres {', '.join(sorted(after))}; "
                             "a song keeps one genre (move it from its genre folder to change genre)")
        self.genres[fp] = after

    @staticmethod
    def _rename(item, source, kind, action):
        """(file name, tags) for the destination: edited in the Inbox, the file gets the new name and tags."""
        file_name = Path(source).name
        if ("title" in item or "artist" in item) and kind == "inbox" and action == "move":
            artist, title = (item.get("artist") or "").strip(), (item.get("title") or "").strip()
            if not title:
                raise ValueError(f"{source}: the title cannot be empty")
            return (track_file_name(artist, title, Path(source).suffix) or file_name,
                    {"artist": artist or None, "title": title})
        return file_name, {}

    def _add(self, item):
        source, to, action, to_kind, to_name = self._parse(item)
        if action == "move" and source in self.located:
            raise ValueError(f"{source}: moved twice in one plan; list one move per file")
        current = self.located.get(source, source)
        kind, folder = classify(Path(current))
        fp = self.fp_of[source]
        self._check_move_out(source, kind, action, to_kind)
        existing = [c["path"] for c in self.songs[fp]
                    if str(Path(c["path"]).parent) == to and c["path"] not in self.gone]
        if existing or (to, fp) in self.planned:
            self.plan.steps.append(Step("skip", str(self.root / current), "",
                                        f"already there: {existing[0] if existing else self.planned[(to, fp)]}"))
            return
        self._check_genre(source, fp, kind, folder, action, to_kind, to_name)
        file_name, tags = self._rename(item, source, kind, action)
        dest = str(Path(to) / file_name)
        if ((self.root / dest).exists() and dest not in self.gone) or dest in self.planned.values():
            raise ValueError(f"{source}: a different file named {Path(dest).name!r} already exists in {to}")
        self.planned[(to, fp)] = dest
        if action == "move":
            self.located[source] = dest
            self.gone.add(current)
        if kind == "genre" and action == "move":
            self.plan.notes.append(f"{source}: if Rekordbox already imported it, re-link it after the move")
        self.plan.steps.append(Step(action, str(self.root / current), str(self.root / dest), tags=tags))


def plan_remove(root, trash, tracks, paths):
    """Send library copies (files or folders, relative to the root) to the Trash."""
    root, trash = Path(root), Path(trash)
    songs = by_song(tracks)
    fp_of = {t["path"]: t["fp"] for t in tracks}
    trash_dir = trash / f"djhub-{stamp()}"
    plan = Plan("remove")
    expanded = []
    for rel in paths:
        rel = rel.rstrip("/")
        if rel not in ("", ".") and (root / rel).is_dir():
            inside = sorted(p for p in fp_of if p.startswith(rel + "/"))
            expanded.extend(inside or [rel])
        else:
            expanded.append(rel)
    removed = set()
    for rel in dict.fromkeys(expanded):   # a file listed twice (or inside a listed folder) is planned once
        if rel not in fp_of:
            plan.problems.append(f"not a library audio file: {rel}")
            continue
        kind, _ = classify(Path(rel))
        if kind == "genre":
            left = [c for c in songs[fp_of[rel]] if c["kind"] == "genre" and c["path"] not in removed]
            if len(left) < 2:
                plan.problems.append(f"{rel}: this is the song's only genre copy; move it to another genre instead")
                continue
            plan.notes.append(f"{rel}: if Rekordbox already imported it, it will show as missing")
        removed.add(rel)
        plan.steps.append(Step("move", str(root / rel), str(trash_dir / rel), label="trash"))
    return plan


def _inside_sources(sources, raw):
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"download paths must be absolute: {raw}")
    resolved = path.resolve()
    if not any(Path(src).resolve() in resolved.parents for src in sources):
        raise ValueError(f"not inside a download folder ({', '.join(map(str, sources))}): {raw}")
    return resolved


def _same_audio(path, candidates):
    """Library paths among `candidates` whose encoded audio is identical to `path` (tags may differ)."""
    if not candidates:
        return []
    wanted = audio_hash(path)
    if not wanted:
        return []
    return [t["path"] for t in candidates if audio_hash(t["abs"]) == wanted]


def _check_download(sources, raw, to, signatures, seen):
    """The resolved path of a download picked for `to`, or ValueError / OSError saying what is wrong."""
    path = _inside_sources(sources, raw)
    if not path.is_file() or path.suffix.lower() not in AUDIO:
        raise ValueError(f"missing or not an audio file: {raw}")
    if to == INBOX and path.suffix.lower() != ".mp3":
        raise ValueError(f"only MP3 files go to {INBOX}: {raw}")
    if str(path) in seen:
        raise ValueError(f"listed twice: {raw}")
    signature = signatures.get(raw)
    stat = path.stat()
    if signature and [str(stat.st_size), str(stat.st_mtime_ns)] != [str(v) for v in signature]:
        raise ValueError(f"changed since the review (review it again): {raw}")
    return path


def _intake_notes(path, by_fp, by_name):
    """What the library already has of a download going to the Inbox (a note, never a block)."""
    fp = quick_fingerprint(path)
    if fp in by_fp:
        return [f"the same file is already in the library: {by_fp[fp]}"]
    info = describe_file(path)
    candidates = by_name.get((normalize(info["artist"]), normalize(info["title"])), [])
    same = _same_audio(path, candidates)   # a re-tagged library copy has another fingerprint, not other audio
    other = [t["path"] for t in candidates if t["path"] not in same]
    notes = []
    if same:
        notes.append(f"the same audio is already in the library: {', '.join(same)}")
    if other:
        notes.append(f"possible upgrade of {', '.join(other)}")
    return notes


def plan_intake(root, sources, tracks, picks):
    """Reviewed downloads: the kept version to 00 Inbox, the others to 00 Rejected/<song>.

    picks: [{"song": "Artist - Title", "keep": "/abs/file" | None,
             "reject": ["/abs/file", ...], "signatures": {"/abs/file": [size, "mtime_ns"]},
             "artist": "...", "title": "..."}]
    The kept file is renamed to 'Artist - Title.ext' when artist/title are given.
    Rejected files keep their download names.
    A song with any problem is skipped as a whole.
    """
    root = Path(root)
    library = [t for t in tracks if t["kind"] != "rejected"]
    by_fp = {t["fp"]: t["path"] for t in library}
    by_name = {}
    for t in library:
        if t["title"]:
            by_name.setdefault((normalize(t["artist"]), normalize(t["title"])), []).append(t)
    plan = Plan("intake")
    taken, seen = set(), set()
    for pick in picks:
        song = pick.get("song") or ""
        signatures = pick.get("signatures") or {}
        entries = [(pick["keep"], INBOX)] if pick.get("keep") else []
        entries += [(r, f"{REJECTED}/{song_folder_name(song)}") for r in pick.get("reject") or []]
        own_steps, own_problems = [], []
        own_dests, own_seen = set(), set()
        for raw, to in entries:
            try:
                path = _check_download(sources, raw, to, signatures, seen | own_seen)
            except (ValueError, OSError) as error:
                own_problems.append(str(error))
                continue
            name = path.name
            if to == INBOX and pick.get("title"):
                name = track_file_name(pick.get("artist"), pick["title"], path.suffix) or name
            dest = f"{to}/{name}"
            if (root / dest).exists() or dest.casefold() in taken or dest.casefold() in own_dests:
                own_problems.append(f"{name}: a file with this name is already in {to}")
                continue
            own_dests.add(dest.casefold())
            own_seen.add(str(path))
            tags, fill = {}, {}
            if to == INBOX and pick.get("title"):
                tags = {"artist": pick.get("artist") or "", "title": pick["title"]}
                fill = {k: pick[k] for k in ("album", "year") if pick.get(k)}
            own_steps.append(Step("move", str(path), str(root / dest), label="inbox" if to == INBOX else "reject",
                                  tags=tags, fill_tags=fill))
        if own_problems:
            plan.problems += [f"{song or '(no song name)'}: {p} (song skipped)" for p in own_problems]
            continue
        for step in own_steps:
            taken.add(str(Path(step.dest).relative_to(root)).casefold())
            seen.add(step.source)
            if step.label == "inbox":
                plan.notes += [f"{song}: {note}" for note in _intake_notes(Path(step.source), by_fp, by_name)]
        plan.steps += own_steps
    return plan


def plan_rename(root, tracks, items):
    """Change artist and title of files in 00 Inbox: the file becomes 'Artist - Title.mp3'
    and the ID3 tags are written to match.

    items: [{"source": rel path, "artist": str, "title": str}]. Only Inbox files, because a song
    kept elsewhere may have copies, and copies must keep identical bytes."""
    root = Path(root)
    known = {t["path"]: t for t in tracks}
    plan = Plan("rename")
    taken = set()
    for item in items:
        source = item.get("source", "")
        track = known.get(source)
        if track is None or track["kind"] != "inbox":
            plan.problems.append(f"{source}: only files in 00 Inbox can be renamed here")
            continue
        path = Path(track["abs"])
        title = (item.get("title") or "").strip()
        if not title:
            plan.problems.append(f"{source}: the title cannot be empty")
            continue
        has_artist = item.get("artist") is not None   # no artist key: keep the current artist tag
        artist = (item["artist"] if has_artist else track["artist"] or "").strip()
        name = track_file_name(artist, title, path.suffix) or path.name
        dest = path.with_name(name)
        clash = dest.exists() and dest != path and not _same_file(dest, path)
        if clash or str(dest).casefold() in taken:
            plan.problems.append(f"{source}: a file named {name!r} already exists in 00 Inbox")
            continue
        taken.add(str(dest).casefold())
        tags = {"title": title}
        if has_artist:
            tags["artist"] = artist or None
        if dest == path:
            have = read_tags(path)
            if have.get("title", "") == title and (not has_artist or have.get("artist", "") == artist):
                continue
            plan.steps.append(Step("tags", str(path), str(path), tags=tags))
        else:
            plan.steps.append(Step("move", str(path), str(dest), label="rename", tags=tags))
    return plan


def plan_undo(root, trash, batch_label, ops):
    """Revert applied operations (newest first). ops: [{"action", "source", "dest"}] with absolute paths.

    A copy is undone by moving the copy to the Trash, a move by moving it back.
    """
    trash_dir = Path(trash) / f"djhub-undo-{batch_label}"
    root = Path(root)
    plan = Plan("undo")
    for op in reversed(ops):
        source, dest = Path(op["source"]), Path(op["dest"])
        if op["action"] == "tags":
            if not dest.exists():
                plan.problems.append(f"no longer there: {dest}")
            elif op.get("tags_before"):
                plan.steps.append(Step("tags", str(dest), str(dest), label="restore tags",
                                       tags=op["tags_before"]))
            continue
        if op["action"] == "copy":
            try:
                rel = dest.relative_to(root)
            except ValueError:
                rel = Path(dest.name)
            step = Step("move", str(dest), str(trash_dir / rel), label="trash copy")
        else:
            step = Step("move", str(dest), str(source), label="restore" if op.get("trash") else "move back",
                        tags=op.get("tags_before") or {})
        if not Path(step.source).exists():
            plan.problems.append(f"no longer there: {step.source}")
            continue
        if Path(step.dest).exists() and not _same_file(step.source, step.dest):
            plan.problems.append(f"something is already at {step.dest}")
            continue
        plan.steps.append(step)
    return plan


def plan_tags(root, tracks, genre=False):
    """Fix ID3 tags in place so Rekordbox shows them right: a missing artist or title is taken
    from the file name. With `genre=True` the genre tag also becomes the name of the song's
    genre folder (this rewrites most files, so it is a separate choice).

    Every copy of a song gets the same edit (copies are byte-identical, and song identity is
    the file fingerprint, which includes the tag bytes). Rejected versions are left alone."""
    plan = Plan("tags")
    for copies in by_song(tracks).values():
        copies = active(copies)
        if not copies or not copies[0]["abs"].lower().endswith(".mp3"):
            continue
        first = sorted(copies, key=lambda c: c["path"])[0]
        have = read_tags(first["abs"])
        guess = guess_from_filename(Path(first["path"]).stem)
        # The file name is 'Artist - Title': everything after the first ' - ' is the title.
        stem = re.sub(r"^\s*\(?\d{1,3}\)?\s*[-.\s_]\s*", "", Path(first["path"]).stem)
        if guess.get("artist") and " - " in stem:
            guess["title"] = stem.split(" - ", 1)[1].strip()
        wanted = {}
        for key in ("artist", "title"):
            if not have.get(key) and guess.get(key):
                wanted[key] = guess[key]
        genres = genre_folders(copies)
        if genre and len(genres) == 1 and have.get("genre") != genres[0]:
            wanted["genre"] = genres[0]
        if not wanted:
            continue
        for copy in sorted(copies, key=lambda c: c["path"]):
            plan.steps.append(Step("tags", copy["abs"], copy["abs"], tags=dict(wanted)))
    return plan


def plan_retag(root, tracks, items):
    """Correct the artist or title tag of songs already sorted (only tags change, never the file name).

    items: [{"source": rel path, "artist": str, "title": str}]; a missing key keeps that tag.
    Every copy of the song gets the same edit, so copies stay byte-identical."""
    known = {t["path"]: t for t in tracks}
    songs = by_song(tracks)
    plan = Plan("retag")
    seen = set()
    for item in items:
        source = item.get("source", "")
        track = known.get(source)
        if track is None or track["kind"] not in ("genre", "session"):
            plan.problems.append(f"{source}: not a song in Genres or Sessions")
            continue
        if track["fp"] in seen:
            plan.problems.append(f"{source}: the same song is listed twice")
            continue
        seen.add(track["fp"])
        wanted = {key: (item[key] or "").strip() or None for key in ("artist", "title") if key in item}
        if wanted.get("title", "x") is None:
            plan.problems.append(f"{source}: the title cannot be empty")
            continue
        copies = sorted(active(songs[track["fp"]]), key=lambda c: c["path"])
        have = read_tags(copies[0]["abs"])
        wanted = {k: v for k, v in wanted.items() if (have.get(k) or None) != v}
        for copy in copies if wanted else []:
            plan.steps.append(Step("tags", copy["abs"], copy["abs"], label="retag", tags=dict(wanted)))
    return plan


# --- Running a plan ----------------------------------------------------------------------


def _remove_empty_dirs(root, folder):
    """Remove now-empty folders inside 00 Rejected (only truly empty ones)."""
    rejected = (Path(root) / REJECTED).resolve()
    folder = Path(folder).resolve()
    while folder != rejected and rejected in folder.parents:
        try:
            folder.rmdir()
        except OSError:
            return
        folder = folder.parent


def _preflight(plan):
    """Check the whole plan before touching anything, so a bad step cannot leave a half-done batch.
    Steps may use a file an earlier step creates, so the check follows the plan in order."""
    created, vanished, dests = set(), set(), set()
    for step in plan.runnable():
        if step.action == "tags":
            continue
        source, dest = step.source, step.dest
        if source in vanished or (source not in created and not Path(source).exists()):
            raise FileNotFoundError(f"missing: {source}")
        key = dest.casefold()
        if key in dests or (Path(dest).exists() and dest not in vanished
                            and not (step.action == "move" and _same_file(source, dest))):
            raise FileExistsError(f"refusing to overwrite {dest}")
        dests.add(key)
        created.add(dest)
        if step.action == "move":
            vanished.add(source)
            created.discard(source)


def _copy(source, dest):
    """Copy to a temporary name and rename it, so a full disk never leaves a partial file at `dest`."""
    temp = dest.with_name(f".{dest.name}.djhub-tmp")
    try:
        shutil.copy2(source, temp)
        os.replace(temp, dest)
    finally:
        temp.unlink(missing_ok=True)


def execute(root, plan, on_done=None, on_start=None):
    """Run the plan's steps in order. `on_start(step)` is called just before each step (so the
    caller can write its intent down first) and `on_done(step)` right after it."""
    _preflight(plan)
    done = []
    for step in plan.runnable():
        dest = Path(step.dest)
        if on_start:
            on_start(step)
        if step.action == "tags":
            try:
                step.tags_before = write_tags(dest, step.tags, step.fill_tags)
            except Exception as error:
                step.note = f"Tags not written: {error}"
            done.append(step)
            if on_done:
                on_done(step)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        same = step.action == "move" and _same_file(step.source, dest)
        if dest.exists() and not same:
            raise FileExistsError(f"refusing to overwrite {dest}")
        if step.action == "copy":
            _copy(step.source, dest)
        else:
            if same and step.source != step.dest:
                os.rename(step.source, step.dest)
            else:
                shutil.move(step.source, str(dest))
            _remove_empty_dirs(root, Path(step.source).parent)
        if step.tags or step.fill_tags:
            try:
                step.tags_before = write_tags(dest, step.tags, step.fill_tags)
            except Exception as error:  # the move is done and logged; report, do not stop the batch
                step.note = f"Tags not written: {error}"
        done.append(step)
        if on_done:
            on_done(step)
    return done
